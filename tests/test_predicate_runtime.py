import json
from types import SimpleNamespace

import pytest

from docs.experiments import predicate_runtime_compare_v1 as comparison
from docs.experiments import predicate_runtime_feedback_v1 as runtime
from docs.experiments.predicate_trace_probe_v1 import value
from evals.runner import digest, snapshot
from evals.runtime import Events


@pytest.fixture
def case(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'example.py').write_text(
        'def locate(iterable, pred, window_size=1):\n'
        '    unrelated = "do-not-capture-this-local"\n'
        '    items = tuple(iterable)\n'
        '    if len(items) < window_size:\n'
        '        items += (object(),)\n'
        '    return [0] if pred(*items) else []\n', encoding='utf-8')
    harness = tmp_path / 'public'
    harness.mkdir()
    (harness / 'test_admission.py').write_text(
        'import unittest\nfrom example import locate\n'
        'class Reproduce(unittest.TestCase):\n'
        '    def test_tail(self):\n'
        '        def predicate(*items): return sum(items) == 7\n'
        '        self.assertEqual(locate([4], predicate, window_size=2), [])\n'
        'class Preserve(unittest.TestCase):\n'
        '    def test_normal(self):\n'
        '        self.assertEqual(locate([7], lambda *items: sum(items) == 7), [0])\n'
        'class Target(unittest.TestCase):\n'
        '    def test_private(self): raise RuntimeError("private-must-not-run")\n', encoding='utf-8')
    job = {'harness': str(harness), 'harness_hash': digest(snapshot(harness)), 'source_root': '.',
           'package': 'example', 'allowed_files': ['example.py']}
    outcomes = {'public': {'Reproduce': {'passed': False, 'tests_run': 1},
                           'Preserve': {'passed': True, 'tests_run': 1}}}
    return workspace, job, outcomes


def test_public_callback_arguments_return_and_exception_are_observed(case, tmp_path):
    workspace, job, outcomes = case
    before = digest(snapshot(workspace))
    data = runtime.observe(workspace, job, tmp_path / 'probe', outcomes)
    assert data is not None
    failed, passed = data['records']
    operation = failed['operations'][0]
    assert operation['input']['items'] == [4] and operation['window_size'] == 2
    call = operation['predicate_calls'][0]
    assert call['arguments']['items'] == [4, {'type': 'object', 'value': 'not captured'}]
    assert call['exception_type'] == 'TypeError'
    assert passed['operations'][0]['predicate_calls'][0]['return'] is True
    text = json.dumps(data)
    assert 'do-not-capture-this-local' not in text and 'private-must-not-run' not in text
    assert digest(snapshot(workspace)) == before


def test_trace_result_mismatch_falls_back(case, tmp_path):
    workspace, job, outcomes = case
    outcomes['public']['Reproduce']['passed'] = True
    assert runtime.observe(workspace, job, tmp_path / 'probe', outcomes) is None


def test_tampered_public_checks_are_rejected(case, tmp_path):
    workspace, job, outcomes = case
    from pathlib import Path
    (Path(job['harness']) / 'test_admission.py').write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='harness changed'):
        runtime.observe(workspace, job, tmp_path / 'probe', outcomes)


def test_serialization_does_not_run_user_repr_or_iterator():
    class Dangerous:
        def __repr__(self):
            raise AssertionError('repr executed')
        def __iter__(self):
            raise AssertionError('iterator executed')
    assert value(Dangerous()) == {'type': 'Dangerous', 'value': 'not captured'}
    data = value(list(range(20)))
    assert len(data['items']) == 12 and data['omitted'] == 8


def test_runtime_hook_only_adds_observations_and_restores_original(tmp_path, monkeypatch):
    original = runtime.guarded.feedback
    refresh = runtime.previous.refresh_seeds
    monkeypatch.setattr(runtime.guarded, 'feedback', lambda *args: {'observations': 'unchanged'})
    hook = runtime.guarded.feedback
    monkeypatch.setattr(runtime, 'observe', lambda *args: {'records': ['public observation']})
    def run(llm, job, events):
        assert runtime.previous.refresh_seeds is refresh
        result = runtime.guarded.feedback({}, None, {}, tmp_path)
        assert result['observations'] == 'unchanged'
        assert result['public_runtime_observations']['records'] == ['public observation']
        raise RuntimeError('worker failed')
    monkeypatch.setattr(runtime.guarded, 'run_candidate', run)
    with pytest.raises(RuntimeError, match='worker failed'):
        runtime.run_candidate(None, {}, Events(tmp_path / 'trace.jsonl', 'test'))
    assert runtime.guarded.feedback is hook and hook is not original


def test_shared_first_replay_charges_recorded_usage_then_calls_model(tmp_path):
    messages = [{'role': 'user', 'content': 'same initial context'}]
    (tmp_path / 'initial-messages.json').write_text(json.dumps(messages), encoding='utf-8')
    (tmp_path / 'initial-response.txt').write_text('{"edits": []}', encoding='utf-8')
    (tmp_path / 'worker-result.json').write_text(json.dumps({'provider_calls': [
        {'prompt_tokens': 100, 'completion_tokens': 10, 'finish_reason': 'stop'}]}), encoding='utf-8')
    provider = SimpleNamespace(calls=[], model='qwen')
    def chat(messages, tools):
        provider.calls.append({'total_tokens': 20})
        return 'fresh second response'
    provider.chat = chat
    shared = comparison.SharedFirstProvider(provider, tmp_path)
    response = shared.chat(messages, [])
    assert response.prompt_tokens == 100 and response.completion_tokens == 10
    assert shared.calls[0]['replayed']
    assert shared.chat([], []) == 'fresh second response'
    assert shared.calls[1]['replayed'] is False


def test_shared_first_rejects_different_prompt(tmp_path):
    (tmp_path / 'initial-messages.json').write_text('[]', encoding='utf-8')
    shared = comparison.SharedFirstProvider(SimpleNamespace(calls=[], model='qwen'), tmp_path)
    with pytest.raises(ValueError, match='request differs'):
        shared.chat([{'role': 'user', 'content': 'different'}], [])


def test_shared_feedback_keeps_identical_text_and_rejects_changed_checks(case, tmp_path):
    workspace, job, _outcomes = case
    outcomes = {suite: {group: {'passed': group == 'Preserve', 'tests_run': 1,
                               'failures': 0, 'errors': int(group == 'Reproduce')}
                       for group in ('Reproduce', 'Preserve')} for suite in ('public', 'frozen')}
    from pathlib import Path
    job.update(shared_first=str(tmp_path), shared_candidate_hash=digest(snapshot(workspace)))
    feedback = {'observations': 'Fixed original log with elapsed 0.001s',
                'test_code': (Path(job['harness']) / 'test_admission.py').read_text(encoding='utf-8')}
    (tmp_path / 'feedback-messages.json').write_text(json.dumps([{}, {'content': json.dumps(
        {'public_check_feedback': feedback})}]), encoding='utf-8')
    (tmp_path / 'worker-result.json').write_text(json.dumps({'initial_checks': outcomes}), encoding='utf-8')
    assert comparison.shared_feedback(outcomes, workspace, job, tmp_path) == feedback
    outcomes['frozen']['Reproduce']['errors'] = 2
    with pytest.raises(ValueError, match='execution differs'):
        comparison.shared_feedback(outcomes, workspace, job, tmp_path)
