import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from docs.experiments import frozen_feedback_v1 as guard
from docs.experiments.frozen_feedback_replay_v1 import RecordedAnswers, answer_path
from evals.runner import digest, snapshot
from evals.runtime import Events


def outcomes(passed, **kwargs):
    return {label: {group: dict(passed=passed, timed_out=False, tests_run=1, failures=int(not passed),
                                errors=0, skipped=0, **kwargs) for group in ('Reproduce', 'Preserve')}
            for label in ('public', 'frozen')}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'code.py').write_text('original', encoding='utf-8')
    job = {'workspace': str(workspace), 'description': 'public behavior', 'allowed_files': ['code.py'],
           'evidence': [], 'package': 'example', 'source_root': '.', 'original_hash': digest(snapshot(workspace)),
           'description_hash': hashlib.sha256(b'public behavior').hexdigest()}
    for name in ('harness', 'frozen_harness'):
        path = tmp_path / name
        path.mkdir()
        (path / 'test_admission.py').write_text('public checks', encoding='utf-8')
        job[name], job[name + '_hash'] = str(path), digest(snapshot(path))
    monkeypatch.setattr(guard.previous.repair, 'validate_evidence', lambda *args: None)
    monkeypatch.setattr(guard.previous, 'refresh_seeds', lambda *args: {'evidence': []})
    monkeypatch.setattr(guard, 'feedback', lambda *args: {'test_code': 'public checks', 'observations': 'fixed mismatch'})
    llm = SimpleNamespace(calls=0, metrics=lambda: {'llm_calls': llm.calls})
    events = Events(tmp_path / 'trace.jsonl', 'test')
    return job, llm, events


def requests(monkeypatch, llm, initial='completed', correction='completed'):
    def request(shared, workspace, job, evidence, root, stage, feedback=None):
        assert shared is llm
        llm.calls += 1
        (workspace / 'code.py').write_text(stage, encoding='utf-8')
        return {'status': initial if stage == 'initial' else correction}
    monkeypatch.setattr(guard.previous, 'request', request)


def test_correct_initial_needs_no_second_call(setup, monkeypatch):
    job, llm, events = setup
    requests(monkeypatch, llm)
    monkeypatch.setattr(guard, 'checked', lambda *args: outcomes(True))
    result = guard.run_candidate(llm, job, events)
    assert result['published'] and llm.calls == 1
    assert not result['original_restored']


def test_valid_correction_is_retained(setup, monkeypatch):
    job, llm, events = setup
    requests(monkeypatch, llm)
    monkeypatch.setattr(guard, 'checked', lambda workspace, job, root, stage: outcomes(stage == 'corrected'))
    result = guard.run_candidate(llm, job, events)
    assert result['published'] and result['correction_retained']
    assert llm.calls == 2
    assert (Path(job['workspace']) / 'code.py').read_text() == 'feedback'


def test_legacy_pass_frozen_fail_is_not_published(setup, monkeypatch):
    job, llm, events = setup
    requests(monkeypatch, llm)
    def checked(*args):
        checks = outcomes(True)
        checks['frozen'] = outcomes(False)['frozen']
        return checks
    monkeypatch.setattr(guard, 'checked', checked)
    result = guard.run_candidate(llm, job, events)
    assert result['status'] == 'failed_public_validation'
    assert not result['published'] and result['original_restored']
    assert llm.calls == 2
    assert (Path(job['workspace']) / 'code.py').read_text() == 'original'


@pytest.mark.parametrize('status', ['invalid_patch', 'budget_exceeded', 'output_truncated'])
def test_failed_second_attempt_restores_starting_source(setup, monkeypatch, status):
    job, llm, events = setup
    requests(monkeypatch, llm, correction=status)
    monkeypatch.setattr(guard, 'checked', lambda *args: outcomes(False))
    result = guard.run_candidate(llm, job, events)
    assert not result['correction_retained'] and result['original_restored']
    assert llm.calls == 2


def test_validation_exception_never_leaves_wrong_source(setup, monkeypatch):
    job, llm, events = setup
    requests(monkeypatch, llm)
    monkeypatch.setattr(guard, 'checked', lambda *args: (_ for _ in ()).throw(RuntimeError('runner failed')))
    result = guard.run_candidate(llm, job, events)
    assert result['status'] == 'agent_error' and result['original_restored']
    assert not result['published']


def test_zero_tests_do_not_trigger_feedback_or_publish(setup, monkeypatch):
    job, llm, events = setup
    requests(monkeypatch, llm)
    empty = outcomes(False)
    empty['frozen']['Reproduce']['tests_run'] = 0
    monkeypatch.setattr(guard, 'checked', lambda *args: empty)
    result = guard.run_candidate(llm, job, events)
    assert llm.calls == 1 and result['original_restored']


@pytest.mark.parametrize('field', ['harness', 'frozen_harness', 'description', 'workspace'])
def test_tampered_inputs_rejected_before_first_request(setup, monkeypatch, field):
    job, llm, events = setup
    requests(monkeypatch, llm)
    if field in ('harness', 'frozen_harness'):
        (Path(job[field]) / 'test_admission.py').write_text('modified', encoding='utf-8')
    elif field == 'description':
        job[field] += ' changed'
    else:
        (Path(job[field]) / 'code.py').write_text('external change', encoding='utf-8')
    with pytest.raises(ValueError):
        guard.run_candidate(llm, job, events)
    assert llm.calls == 0


def test_workspace_outside_owned_task_is_not_replaced(setup, tmp_path):
    job, llm, events = setup
    outside = tmp_path / 'user-project'
    outside.mkdir()
    (outside / 'keep').write_text('keep', encoding='utf-8')
    job['workspace'] = str(outside)
    with pytest.raises(ValueError, match='owned'):
        guard.run_candidate(llm, job, events)
    assert (outside / 'keep').read_text() == 'keep'


def test_truncated_provider_answer_stays_rejected(tmp_path):
    provider = tmp_path / 'provider-call-01'
    provider.mkdir()
    response = provider / 'response.txt'
    response.write_text('partial patch', encoding='utf-8')
    assert answer_path(tmp_path, 'initial', 'output_truncated') == response
    llm = RecordedAnswers([('partial patch', 'output_truncated')])
    with pytest.raises(guard.previous.baseline.InvalidCompletion):
        llm.chat([])
    assert llm.metrics()['llm_calls'] == 0


def test_missing_completed_answer_is_not_silently_replayed(tmp_path):
    assert answer_path(tmp_path, 'initial', 'budget_exceeded') is None
    with pytest.raises(ValueError, match='Missing recorded'):
        answer_path(tmp_path, 'initial', 'completed')
