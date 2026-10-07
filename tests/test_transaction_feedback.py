import json
import sys

import pytest

from corecoder.llm import LLMResponse, ToolCall
from docs.experiments import thinking_calibration_v1 as calibration
from docs.experiments import transaction_feedback_probe_v1 as probe
from docs.experiments import transaction_feedback_v1 as feedback
from evals.runtime import BudgetLLM, Events
from evals.schema import RunConfig

BAD = json.dumps({'edits': [{'file': 'app.py', 'old': 'return 1', 'new': 'return ('}]})
GOOD = json.dumps({'edits': [{'file': 'app.py', 'old': 'return 1', 'new': 'return 2'}]})


class Replies:
    model = 'test-model'

    def __init__(self, replies, inspect=None, usage=20):
        self.replies, self.inspect, self.usage = iter(replies), inspect, usage
        self.calls = 0
    def chat(self, messages, tools=None):
        self.calls += 1
        if self.inspect:
            self.inspect(self.calls, messages)
        value = next(self.replies)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, LLMResponse):
            return value
        return LLMResponse(content=value, prompt_tokens=self.usage, completion_tokens=self.usage)


def setup(tmp_path, replies, policy='diagnostic', token_budget=15000, inspect=None, usage=20):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'app.py').write_bytes(b'def f():\n    return 1\n')
    job = {'workspace': str(workspace), 'description': 'f must return 2.', 'allowed_files': ['app.py'],
           'files': calibration.evidence(workspace), 'policy': policy, 'test_python': sys.executable,
           'imports': [{'module': 'app', 'root': '.', 'path': 'app.py'}]}
    output = tmp_path / 'run'
    output.mkdir()
    events = Events(output / 'trace.jsonl', 'test-feedback')
    provider = Replies(replies, inspect, usage)
    llm = BudgetLLM(provider, RunConfig(token_budget=token_budget, max_output_tokens=256), events)
    return workspace, job, events, provider, llm


@pytest.mark.parametrize('policy', feedback.POLICIES)
def test_one_feedback_uses_unchanged_source_and_same_budget(tmp_path, policy):
    def inspect(number, messages):
        if number == 2:
            assert (workspace / 'app.py').read_bytes() == b'def f():\n    return 1\n'
            data = json.loads(messages[1]['content'])
            assert 'validation' in data['transaction_feedback'] if policy == 'diagnostic' else 'validation' not in data['transaction_feedback']
            assert data['files'][0]['content'] == 'def f():\n    return 1\n'
    workspace, job, events, provider, llm = setup(tmp_path, [BAD, GOOD], policy, inspect=inspect)
    result = feedback.run_candidate(llm, job, events)
    assert result['transaction_accepted'] and provider.calls == 2
    assert result['feedback_attempts'] == 1 and result['metrics']['budget_accounted_tokens'] == 80
    assert (workspace / 'app.py').read_bytes() == b'def f():\n    return 2\n'


def test_two_rejections_never_trigger_third_call(tmp_path):
    workspace, job, events, provider, llm = setup(tmp_path, [BAD, BAD, GOOD])
    result = feedback.run_candidate(llm, job, events)
    assert not result['transaction_accepted'] and provider.calls == 2
    assert len(result['attempts']) == 2 and (workspace / 'app.py').read_bytes() == b'def f():\n    return 1\n'


def test_valid_first_patch_skips_feedback(tmp_path):
    _, job, events, provider, llm = setup(tmp_path, [GOOD])
    result = feedback.run_candidate(llm, job, events)
    assert result['transaction_accepted'] and result['feedback_attempts'] == 0 and provider.calls == 1


def test_feedback_is_blocked_by_shared_cumulative_budget(tmp_path):
    _, job, events, provider, llm = setup(tmp_path, [BAD, GOOD], token_budget=3000, usage=1400)
    result = feedback.run_candidate(llm, job, events)
    assert result['status'] == 'budget_exceeded' and provider.calls == 1
    assert not result['transaction_accepted'] and result['metrics']['budget_accounted_tokens'] == 2800


def test_seeded_probe_counts_only_fresh_model_call(tmp_path):
    _, job, events, provider, llm = setup(tmp_path, [GOOD])
    result = feedback.run_candidate(llm, job, events, seed_patch=BAD)
    assert result['seeded'] and result['transaction_accepted']
    assert result['attempts'][0]['origin'] == 'synthetic-seed' and provider.calls == 1
    assert result['metrics']['llm_calls'] == 1


def test_provider_failure_does_not_retry(tmp_path):
    _, job, events, provider, llm = setup(tmp_path, [OSError('offline'), GOOD])
    result = feedback.run_candidate(llm, job, events)
    assert result['status'] == 'provider_error' and provider.calls == 1


def test_unexpected_tools_do_not_execute_or_retry(tmp_path):
    response = LLMResponse(content=GOOD, tool_calls=[ToolCall('1', 'bash', {'command': 'anything'})])
    workspace, job, events, provider, llm = setup(tmp_path, [response, GOOD])
    result = feedback.run_candidate(llm, job, events)
    assert result['status'] == 'unexpected_tools' and provider.calls == 1
    assert (workspace / 'app.py').read_bytes() == b'def f():\n    return 1\n'


def test_truncated_valid_json_is_not_applied_before_feedback(tmp_path):
    def inspect(number, messages):
        provider.telemetry = {'done_reason': 'length' if number == 1 else 'stop'}
        if number == 2:
            assert (workspace / 'app.py').read_bytes() == b'def f():\n    return 1\n'
    workspace, job, events, provider, llm = setup(tmp_path, [GOOD, GOOD], inspect=inspect)
    result = feedback.run_candidate(llm, job, events)
    assert result['attempts'][0]['status'] == 'output_truncated'
    assert result['transaction_accepted'] and provider.calls == 2


def test_empty_final_answer_gets_only_one_feedback(tmp_path):
    _, job, events, provider, llm = setup(tmp_path, ['', GOOD])
    result = feedback.run_candidate(llm, job, events)
    assert result['attempts'][0]['status'] == 'empty_final_answer'
    assert result['transaction_accepted'] and provider.calls == 2


def test_source_change_stops_feedback(tmp_path, monkeypatch):
    workspace, job, events, provider, llm = setup(tmp_path, [BAD, GOOD])
    def changed(*args):
        (workspace / 'app.py').write_bytes(b'value = 99\n')
        return {'accepted': False, 'reason': 'source_changed', 'original_unchanged': False}
    monkeypatch.setattr(feedback.guard, 'transact', changed)
    result = feedback.run_candidate(llm, job, events)
    assert result['status'] == 'source_changed' and provider.calls == 1


def test_offline_paired_probe_never_contacts_model_or_exposes_checks(tmp_path, monkeypatch):
    monkeypatch.setattr(calibration, 'identity', lambda *args: pytest.fail('No network in offline probe'))
    output = tmp_path / 'probe'
    probe.run(output)
    report = json.loads((output / 'experiment.json').read_text(encoding='utf-8'))
    assert report['complete'] and report['model_calls'] == 0 and len(report['runs']) == 6
    assert all(r['verification']['passed'] and r['result']['metrics']['llm_calls'] == 1 for r in report['runs'])
    for task in probe.FAULTS:
        left, right = [json.loads((output / task / policy / 'attempt-02/messages.json').read_text(encoding='utf-8'))
                       for policy in feedback.POLICIES]
        a, b = json.loads(left[1]['content']), json.loads(right[1]['content'])
        assert b['transaction_feedback'].pop('validation')
        assert a == b and left[0] == right[0]
        assert set(a) == {'description', 'allowed_files', 'files', 'transaction_feedback'}
        assert 'test_case' not in json.dumps(a) and 'reference' not in a
