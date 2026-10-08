import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as S

import pytest

from docs.experiments import independent_candidates_v1 as candidate
from evals.runner import digest, snapshot
from evals.runtime import Events


def outcomes(passed, tests=1):
    return {label: {group: {'passed': passed, 'timed_out': False, 'tests_run': tests, 'failures': int(not passed),
                           'errors': 0, 'skipped': 0, 'expected_failures': 0, 'unexpected_successes': 0}
                    for group in ('Reproduce', 'Preserve')} for label in ('public', 'frozen')}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'code.py').write_text('original', encoding='utf-8')
    job = {'workspace': str(workspace), 'description': 'public defect', 'allowed_files': ['code.py'],
           'evidence': [], 'package': 'example', 'source_root': '.', 'original_hash': digest(snapshot(workspace)),
           'description_hash': hashlib.sha256(b'public defect').hexdigest()}
    for name in ('harness', 'frozen_harness'):
        path = tmp_path / name
        path.mkdir()
        (path / 'test_admission.py').write_text('public checks', encoding='utf-8')
        job[name], job[name + '_hash'] = str(path), digest(snapshot(path))
    monkeypatch.setattr(candidate.previous.repair, 'validate_evidence', lambda *args: None)
    llm = S(calls=0, spent=0)
    llm.metrics = lambda: {'llm_calls': llm.calls, 'budget_accounted_tokens': llm.spent}
    return job, llm, Events(tmp_path / 'trace.jsonl', 'test')


def requests(monkeypatch, llm, statuses=('completed', 'completed'), duplicate=False):
    def request(shared, workspace, job, evidence, root, stage, feedback=None):
        assert shared is llm and evidence is job['evidence'] and feedback is None
        assert (workspace / 'code.py').read_text() == 'original'
        llm.calls += 1
        llm.spent += 100
        (workspace / 'code.py').write_text('same' if duplicate else stage, encoding='utf-8')
        return {'status': statuses[llm.calls - 1]}
    monkeypatch.setattr(candidate.previous, 'request', request)


def test_second_candidate_starts_from_original_and_uses_shared_budget(setup, monkeypatch):
    job, llm, events = setup
    requests(monkeypatch, llm)
    monkeypatch.setattr(candidate.guarded, 'checked', lambda *args: outcomes(args[-1] == 'alternative'))
    result = candidate.run_candidate(llm, job, events)
    assert result['published'] and result['selected_candidate'] == 2
    assert result['metrics'] == {'llm_calls': 2, 'budget_accounted_tokens': 200}
    assert (Path(job['workspace']) / 'code.py').read_text() == 'alternative'


def test_first_passing_candidate_is_kept_without_second_call(setup, monkeypatch):
    job, llm, events = setup
    requests(monkeypatch, llm)
    monkeypatch.setattr(candidate.guarded, 'checked', lambda *args: outcomes(True))
    result = candidate.run_candidate(llm, job, events)
    assert result['published'] and result['selected_candidate'] == 1 and llm.calls == 1


def test_duplicate_failed_candidate_is_recorded_without_retesting(setup, monkeypatch):
    job, llm, events = setup
    requests(monkeypatch, llm, duplicate=True)
    checked = []
    monkeypatch.setattr(candidate.guarded, 'checked', lambda *args: checked.append(args[-1]) or outcomes(False))
    result = candidate.run_candidate(llm, job, events)
    assert result['candidates'][1]['duplicate_of'] == 1
    assert checked == ['initial'] and llm.calls == 2
    assert result['original_restored'] and not result['published']


@pytest.mark.parametrize('status', ['invalid_patch', 'output_truncated', 'budget_exceeded'])
def test_unusable_alternative_rolls_back_and_never_publishes(setup, monkeypatch, status):
    job, llm, events = setup
    requests(monkeypatch, llm, statuses=('completed', status))
    monkeypatch.setattr(candidate.guarded, 'checked', lambda *args: outcomes(False))
    result = candidate.run_candidate(llm, job, events)
    assert result['original_restored'] and not result['published'] and llm.calls == 2


def test_public_execution_failure_does_not_trigger_more_generation(setup, monkeypatch):
    job, llm, events = setup
    requests(monkeypatch, llm)
    monkeypatch.setattr(candidate.guarded, 'checked', lambda *args: outcomes(False, tests=0))
    result = candidate.run_candidate(llm, job, events)
    assert result['stop_reason'] == 'public_execution_failure' and llm.calls == 1
    assert result['original_restored']


def test_mutated_public_guard_cannot_authorize_publication(setup, monkeypatch):
    job, llm, events = setup
    requests(monkeypatch, llm)
    def checked(*args):
        (Path(job['harness']) / 'test_admission.py').write_text('changed', encoding='utf-8')
        return outcomes(True)
    monkeypatch.setattr(candidate.guarded, 'checked', checked)
    result = candidate.run_candidate(llm, job, events)
    assert result['status'] == 'agent_error' and result['original_restored'] and not result['published']


def test_frozen_validation_failure_is_not_selected(setup, monkeypatch):
    job, llm, events = setup
    requests(monkeypatch, llm)
    checks = outcomes(True)
    checks['frozen']['Preserve']['passed'] = False
    monkeypatch.setattr(candidate.guarded, 'checked', lambda *args: checks)
    result = candidate.run_candidate(llm, job, events)
    assert not result['published'] and result['original_restored'] and llm.calls == 2


def test_sampling_wire_and_recorded_request_are_identical(tmp_path):
    sent = []
    def create(**kwargs):
        sent.append(kwargs)
        return S(model='qwen3.5:27b', system_fingerprint='test',
                 choices=[S(finish_reason='stop', message=S(content='{"edits": []}', tool_calls=None))],
                 usage=S(prompt_tokens=10, completion_tokens=5, total_tokens=15))
    provider = candidate.SamplingProvider('qwen', Events(tmp_path / 'trace.jsonl', 'test'),
                                         client=S(chat=S(completions=S(create=create))))
    messages = [{'role': 'user', 'content': 'same original source'}]
    provider.chat(messages, tools=[])
    provider.chat(messages, tools=[])
    assert [r['temperature'] for r in sent] == [0, 0.7]
    assert all(r['max_tokens'] == 2048 and r['reasoning_effort'] == 'none' for r in sent)
    for number, request in enumerate(sent, 1):
        assert json.loads((tmp_path / f'provider-call-{number:02d}' / 'request.json').read_text()) == request
    assert provider.calls[0]['prompt_hash'] == provider.calls[1]['prompt_hash']
