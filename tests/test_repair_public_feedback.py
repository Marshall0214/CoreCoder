import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docs.experiments import repair_public_checks_v1 as public
from docs.experiments import repair_public_feedback_v1 as comparison
from docs.experiments import repair_public_feedback_worker_v1 as worker
from evals.runtime import BudgetExceeded, Events


def outcome(passed=False, **extra):
    return {'passed': passed, 'assertion_failure': not passed, 'execution_error': False,
            'timed_out': False, 'tests_run': 4, **extra}


class FakeLLM:
    def __init__(self, responses):
        self.responses, self.messages = responses, []

    def chat(self, messages, tools):
        assert tools == []
        self.messages.append(messages)
        response = self.responses[len(self.messages) - 1]
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=json.dumps(response), tool_calls=[])


@pytest.fixture
def setup(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    path = workspace / 'src/click/formatting.py'
    path.parent.mkdir(parents=True)
    path.write_text('def repair_target():\n    return 1\n', encoding='utf-8')
    data = path.read_bytes()
    harness = tmp_path / 'harness'
    code = public.CHECK_ROOT / public.CHECKS[public.TARGETS[0]]
    record = {'code_sha256': public.repair.audit.sha(code)}
    frozen = public.freeze_harness(public.TARGETS[0], harness, record)
    root = tmp_path / 'run'
    root.mkdir()
    events = Events(root / 'trace.jsonl', 'test')
    name = 'src/click/formatting.py'
    job = {'task_id': public.TARGETS[0], 'policy': 'public-feedback', 'workspace': str(workspace),
           'description': 'repair_target must return the expected public value', 'allowed_files': [name],
           'harness': str(harness), 'harness_hash': frozen, 'check_code_hash': record['code_sha256'],
           'test_python': 'not-used', 'evidence': [{'path': name, 'symbol': 'repair_target', 'start_line': 1,
             'end_line': 2, 'content': data.decode(), 'content_hash': hashlib.sha256(data).hexdigest()}]}
    initial = {'edits': [{'file': name, 'old': 'return 1', 'new': 'return 3'}]}
    final = {'edits': [{'file': name, 'old': 'return 3', 'new': 'value = 2\n    return value'}]}
    calls = []

    def checked(workspace, harness, expected, output, python, task):
        assert expected == public.repair.digest(public.repair.snapshot(harness))
        calls.append(output.name)
        return outcome(output.name == 'public-final'), 'AssertionError: public expected 2'

    monkeypatch.setattr(public, 'check_public', checked)
    return job, events, initial, final, calls


def test_feedback_once_with_updated_source_and_no_first_prompt_checks(setup):
    job, events, initial, final, calls = setup
    llm = FakeLLM([initial, final])
    result = worker.run_candidate(llm, job, events)
    assert result['status'] == 'completed' and result['feedback_attempts'] == 1
    assert result['public_checks']['final']['passed']
    assert calls == ['public-original', 'public-candidate', 'public-final']
    first, second = [json.loads(m[1]['content']) for m in llm.messages]
    assert set(first) == {'description', 'allowed_files', 'fragments'}
    assert 'public_check_feedback' in second
    assert 'return 3' in second['fragments'][0]['content']
    assert second['fragments'][0]['content_hash'] != first['fragments'][0]['content_hash']
    assert 'PublicContract' in second['public_check_feedback']['frozen_test_code']
    assert 'witness' not in json.dumps(second) and 'grading' not in json.dumps(second)
    assert len(llm.messages) == 2


def test_single_control_uses_identical_initial_prompt(setup):
    job, events, initial, _, calls = setup
    job['policy'] = 'single'
    llm = FakeLLM([initial])
    result = worker.run_candidate(llm, job, events)
    fragments = [{k: row.get(k) for k in ('path', 'start_line', 'end_line', 'content_hash', 'content', 'symbol')}
                 for row in job['evidence']]
    expected = [{'role': 'system', 'content': public.repair.patcher.SYMBOL_SYSTEM},
                {'role': 'user', 'content': json.dumps({'description': job['description'],
                 'allowed_files': job['allowed_files'], 'fragments': fragments}, ensure_ascii=False)}]
    assert llm.messages[0] == expected
    assert result['feedback_attempts'] == 0 and len(llm.messages) == 1
    assert calls == ['public-original', 'public-candidate']


@pytest.mark.parametrize('original,candidate', [
    (outcome(True), outcome()), (outcome(), outcome(True)),
    (outcome(execution_error=True), outcome()), (outcome(), outcome(execution_error=True)),
    (outcome(), outcome(timed_out=True)), (outcome(tests_run=0), outcome()),
    (outcome(assertion_failure=False), outcome())])
def test_invalid_failure_pair_never_triggers_feedback(setup, monkeypatch, original, candidate):
    job, events, initial, _, _ = setup
    outputs = iter([original, candidate])
    monkeypatch.setattr(public, 'check_public', lambda *args: (next(outputs), 'public output'))
    llm = FakeLLM([initial])
    result = worker.run_candidate(llm, job, events)
    assert result['feedback_attempts'] == 0 and len(llm.messages) == 1


def test_invalid_initial_patch_skips_feedback(setup):
    job, events, _, _, calls = setup
    llm = FakeLLM([{'edits': [{'file': job['allowed_files'][0], 'old': 'fabricated', 'new': 'bad'}]}])
    result = worker.run_candidate(llm, job, events)
    assert result['status'] == 'invalid_patch' and result['feedback_attempts'] == 0
    assert calls == ['public-original'] and len(llm.messages) == 1


def test_second_failure_does_not_trigger_third_call(setup, monkeypatch):
    job, events, initial, _, calls = setup
    def failed(*args):
        calls.append(args[3].name)
        return outcome(), 'Public assertion still fails'
    monkeypatch.setattr(public, 'check_public', failed)
    llm = FakeLLM([initial, {'edits': []}])
    result = worker.run_candidate(llm, job, events)
    assert result['feedback_attempts'] == 1 and len(llm.messages) == 2
    assert not result['public_checks']['final']['passed']
    assert calls == ['public-original', 'public-candidate', 'public-final']


def test_budget_stop_preserves_initial_stage_and_requested_feedback(setup):
    job, events, initial, _, _ = setup
    progress = {}
    with pytest.raises(BudgetExceeded):
        worker.run_candidate(FakeLLM([initial, BudgetExceeded('budget exhausted')]), job, events, progress)
    assert progress['initial']['status'] == 'completed'
    assert progress['feedback_attempts'] == 1 and len(progress['stages']) == 1


def test_changed_check_rejected_before_model_call(setup):
    job, events, initial, _, _ = setup
    (Path(job['harness']) / 'test_admission.py').write_text('changed check', encoding='utf-8')
    llm = FakeLLM([initial])
    with pytest.raises(ValueError, match='check differs'):
        worker.run_candidate(llm, job, events)
    assert not llm.messages


def test_public_execution_uses_independent_copy_and_rejects_mutation(tmp_path, monkeypatch):
    source, harness = tmp_path / 'candidate', tmp_path / 'harness'
    source.mkdir()
    (source / 'file.py').write_text('original', encoding='utf-8')
    harness.mkdir()
    (harness / 'test_admission.py').write_text('frozen', encoding='utf-8')
    frozen = public.repair.digest(public.repair.snapshot(harness))

    def mutate(copy, checks, group, logs, python, timeout):
        assert copy != source and (copy / 'file.py').read_text() == 'original'
        (copy / 'file.py').write_text('mutated', encoding='utf-8')
        logs.mkdir()
        (logs / 'stderr.txt').write_text('public failure', encoding='utf-8')
        return {**outcome(), 'stderr': 'stderr.txt'}

    monkeypatch.setattr(public, 'execute', mutate)
    with pytest.raises(ValueError, match='mutated'):
        public.check_public(source, harness, frozen, tmp_path / 'execution', Path('unused'), public.TARGETS[0])
    assert (source / 'file.py').read_text() == 'original'


def test_registry_spans_are_exact_public_description_and_code_is_frozen():
    cases = []
    for name in ('validation-public-tasks-v1.json', 'second-repo-public-tasks-v1.json'):
        cases += json.loads((public.CHECK_ROOT.parent / name).read_text(encoding='utf-8'))['tasks']
    records = public.registry(cases)
    for case in cases:
        if case['task_id'] not in records:
            continue
        for clause in records[case['task_id']]['clauses']:
            start, end = clause['span']
            assert case['description'][start:end] == clause['text']
        assert records[case['task_id']]['code_sha256'] == public.repair.audit.sha(
            public.CHECK_ROOT / public.CHECKS[case['task_id']])


@pytest.mark.parametrize('repeats', [0, 4, True])
def test_repeat_bounds_before_reading_any_inputs(tmp_path, repeats):
    with pytest.raises(ValueError, match='Repeat'):
        comparison.run(tmp_path / 'unused', repeats)
    assert not (tmp_path / 'unused').exists()
