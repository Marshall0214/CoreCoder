import hashlib
import json
import sys

import pytest

from corecoder.llm import LLMResponse
from docs.experiments import unified_feedback_v1 as experiment
from docs.experiments import unified_feedback_worker_v1 as worker
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.schema import RunConfig


def patch(old, new):
    return json.dumps({'edits': [{'file': 'app.py', 'old': old, 'new': new}]})


def outcome(passed=False, error=False, count=1):
    return {'passed': passed, 'assertion_failure': not passed and not error, 'execution_error': error,
            'timed_out': False, 'tests_run': count}


class Replies:
    model = 'test'
    def __init__(self, replies, inspect=None, usage=20):
        self.replies, self.inspect, self.usage = iter(replies), inspect, usage
        self.messages = []
    def chat(self, messages, tools=None):
        self.messages.append(messages)
        if self.inspect:
            self.inspect(messages)
        return LLMResponse(content=next(self.replies), prompt_tokens=self.usage, completion_tokens=self.usage)


def evidence(workspace):
    data = (workspace / 'app.py').read_bytes()
    return [{'path': 'app.py', 'symbol': 'f', 'content': data.decode(), 'start_line': 1,
             'end_line': len(data.splitlines()), 'content_hash': hashlib.sha256(data).hexdigest()}]


def setup(tmp_path, monkeypatch, replies, checks, policy='unified-feedback', inspect=None, usage=20, budget=15000):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'app.py').write_bytes(b'def f():\n    return 1\n')
    harness = tmp_path / 'public-harness'
    harness.mkdir()
    canonical = harness / 'test_admission.py'
    canonical.write_bytes(b'# public-only development check\n')
    monkeypatch.setattr(worker, 'canonical_check', lambda task: canonical)
    sequence = iter(checks)
    checked = []
    def check(workspace, harness, value, root, python, name):
        checked.append(root.name)
        return next(sequence), 'AssertionError: public failure'
    monkeypatch.setattr(worker.public, 'check_public', check)
    def pack(workspace, job):
        return {'evidence': evidence(workspace), 'metadata': {'refreshed': True}}
    monkeypatch.setattr(worker, 'pack_feedback', pack)
    root = tmp_path / 'run'
    root.mkdir()
    events = Events(root / 'trace.jsonl', 'unified-test')
    job = {'workspace': str(workspace), 'description': 'f must return 3.', 'task_id': 'click-usage-empty',
           'allowed_files': ['app.py'], 'evidence': evidence(workspace), 'policy': policy, 'test_python': sys.executable,
           'imports': [{'module': 'app', 'root': '.', 'path': 'app.py'}], 'harness': str(harness),
           'harness_hash': 'mocked', 'check_code_hash': worker.repair.audit.sha(canonical)}
    provider = Replies(replies, inspect, usage)
    llm = BudgetLLM(provider, RunConfig(token_budget=budget, max_output_tokens=256), events)
    return workspace, job, events, provider, llm, checked


def test_public_failure_refreshes_evidence_after_committed_first_patch(tmp_path, monkeypatch):
    args = setup(tmp_path, monkeypatch, [patch('return 1', 'return 2'), patch('return 2', 'return 3')],
                 [outcome(), outcome(), outcome(True)])
    workspace, job, events, provider, llm, checked = args
    result = worker.run_candidate(llm, job, events)
    feedback = json.loads(provider.messages[1][1]['content'])
    assert result['feedback_kind'] == 'public' and result['feedback_attempts'] == 1
    assert 'return 2' in feedback['fragments'][0]['content']
    assert feedback['fragments'][0]['content_hash'] != job['evidence'][0]['content_hash']
    assert 'transaction_feedback' not in feedback and result['public_checks']['final']['passed']
    assert checked == ['public-original', 'public-candidate', 'public-final']
    assert (workspace / 'app.py').read_bytes() == b'def f():\n    return 3\n'


@pytest.mark.parametrize('first', [patch('return 1', 'return ('), 'invalid json',
                                  patch('return 1', 'return 1\ndef f():\n    return 2'),
                                  patch('return 1', 'return 1\nimport typing\ndef g(x: typing.str_bytes): pass')])
def test_rejected_edit_feedback_uses_original_source(tmp_path, monkeypatch, first):
    workspace, job, events, provider, llm, checked = setup(
        tmp_path, monkeypatch, [first, patch('return 1', 'return 3')], [outcome(), outcome(True)])
    result = worker.run_candidate(llm, job, events)
    data = json.loads(provider.messages[1][1]['content'])
    assert result['feedback_kind'] == 'transaction' and result['stages'][0]['transaction']['original_unchanged']
    assert data['fragments'][0]['content'] == job['evidence'][0]['content']
    assert 'public_check_feedback' not in data and data['transaction_feedback']['reason']
    assert checked == ['public-original', 'public-final'] and result['status'] == 'completed'
    assert (workspace / 'app.py').read_bytes() == b'def f():\n    return 3\n'


def test_legacy_baseline_does_not_retry_invalid_patch(tmp_path, monkeypatch):
    _, job, events, provider, llm, _ = setup(tmp_path, monkeypatch, ['invalid json', patch('return 1', 'return 3')],
                                           [outcome()], policy='public-feedback')
    result = worker.run_candidate(llm, job, events)
    assert result['status'] == 'invalid_patch' and len(provider.messages) == 1


def test_initial_prompt_exactly_matches_existing_adapter(tmp_path, monkeypatch):
    _, job, events, provider, llm, _ = setup(tmp_path, monkeypatch, [patch('return 1', 'return 3')],
                                           [outcome(), outcome(True)])
    result = worker.run_candidate(llm, job, events)
    fragments = [{key: row.get(key) for key in ('path', 'start_line', 'end_line', 'content_hash', 'content', 'symbol')}
                 for row in job['evidence']]
    expected = [{'role': 'system', 'content': worker.repair.patcher.SYMBOL_SYSTEM}, {'role': 'user', 'content': json.dumps(
        {'description': job['description'], 'allowed_files': job['allowed_files'], 'fragments': fragments}, ensure_ascii=False)}]
    assert provider.messages[0] == expected and result['feedback_attempts'] == 0


@pytest.mark.parametrize('candidate', [outcome(error=True), outcome(count=0), outcome(True)])
def test_no_retry_without_valid_public_assertion_failure(tmp_path, monkeypatch, candidate):
    _, job, events, provider, llm, _ = setup(tmp_path, monkeypatch, [patch('return 1', 'return 2')], [outcome(), candidate])
    result = worker.run_candidate(llm, job, events)
    assert result['feedback_attempts'] == 0 and len(provider.messages) == 1


def test_final_public_failure_never_triggers_third_call(tmp_path, monkeypatch):
    _, job, events, provider, llm, _ = setup(tmp_path, monkeypatch,
        [patch('return 1', 'return 2'), patch('return 2', 'return 4'), patch('return 4', 'return 3')],
        [outcome(), outcome(), outcome()])
    result = worker.run_candidate(llm, job, events)
    assert len(provider.messages) == 2 and not result['public_checks']['final']['passed']


def test_rejected_second_patch_keeps_first_committed_candidate(tmp_path, monkeypatch):
    workspace, job, events, provider, llm, _ = setup(tmp_path, monkeypatch,
        [patch('return 1', 'return 2'), patch('return 2', 'return (')], [outcome(), outcome()])
    result = worker.run_candidate(llm, job, events)
    assert result['status'] == 'invalid_python' and len(provider.messages) == 2
    assert 'final' not in result['public_checks']
    assert (workspace / 'app.py').read_bytes() == b'def f():\n    return 2\n'


def test_import_mutation_is_not_retried(tmp_path, monkeypatch):
    bad = patch('return 1', "return 1\nfrom pathlib import Path\nPath(__file__).write_text('value = 9')")
    _, job, events, provider, llm, _ = setup(tmp_path, monkeypatch, [bad], [outcome()])
    result = worker.run_candidate(llm, job, events)
    assert result['status'] == 'import_mutated_source' and len(provider.messages) == 1


def test_public_feedback_shares_cumulative_budget(tmp_path, monkeypatch):
    workspace, job, events, provider, llm, _ = setup(tmp_path, monkeypatch,
        [patch('return 1', 'return 2'), patch('return 2', 'return 3')], [outcome(), outcome()], usage=1400, budget=3000)
    with pytest.raises(BudgetExceeded):
        worker.run_candidate(llm, job, events)
    assert len(provider.messages) == 1 and llm.metrics()['budget_accounted_tokens'] == 2800
    assert (workspace / 'app.py').read_bytes() == b'def f():\n    return 2\n'


def test_no_public_harness_never_uses_private_grader_for_feedback(tmp_path, monkeypatch):
    _, job, events, provider, llm, _ = setup(tmp_path, monkeypatch, [patch('return 1', 'return 2')], [])
    monkeypatch.setattr(worker, 'canonical_check', lambda task: None)
    result = worker.run_candidate(llm, job, events)
    assert result['feedback_skipped'] == 'no_certified_public_checks' and len(provider.messages) == 1


def test_task_selection_errors_do_not_start_model(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment.preparation, 'prepare', lambda output: ([{'task_id': 'a'}], [{}]))
    monkeypatch.setattr(experiment.repair, 'check_identity', lambda *args: pytest.fail('No model for invalid selection'))
    for tasks in (['unknown'], ['a', 'a']):
        with pytest.raises(ValueError, match='selection'):
            experiment.run(tmp_path / 'output', tasks)
