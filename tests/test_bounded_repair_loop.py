from pathlib import Path

import pytest

from docs.experiments import bounded_repair_loop_v1 as loop
from tests.test_frozen_feedback import outcomes

pytest_plugins = ['tests.test_frozen_feedback']


def sequence(monkeypatch, llm, statuses):
    def request(shared, workspace, job, evidence, root, stage, feedback=None):
        llm.calls += 1
        (workspace / 'code.py').write_text(stage)
        return {'status': statuses[llm.calls - 1], 'error': 'actual edit failure'}
    monkeypatch.setattr(loop.previous, 'request', request)
    monkeypatch.setattr(loop, 'public_feedback', lambda *args: {'observations': 'public failure'})


def test_invalid_patch_recovers_then_third_attempt_passes(setup, monkeypatch):
    job, llm, events = setup
    job['max_calls'] = 4
    sequence(monkeypatch, llm, ['invalid_patch', 'completed', 'completed'])
    seen = []

    def checked(workspace, job, root, stage):
        seen.append(stage)
        return outcomes(stage == 'round-03')

    monkeypatch.setattr(loop.guarded, 'checked', checked)
    result = loop.run_candidate(llm, job, events)
    assert result['published'] and llm.calls == 3
    assert seen == ['round-02', 'round-03']
    assert (events.path.parent / 'round-02-before/code.py').read_text() == 'original'
    assert (Path(job['workspace']) / 'code.py').read_text() == 'round-03'


@pytest.mark.parametrize('limit', [2, 4])
def test_failed_attempts_obey_limit_and_restore_original(setup, monkeypatch, limit):
    job, llm, events = setup
    job['max_calls'] = limit
    sequence(monkeypatch, llm, ['completed'] * limit)
    monkeypatch.setattr(loop.guarded, 'checked', lambda *args: outcomes(False))
    result = loop.run_candidate(llm, job, events)
    assert not result['published'] and result['original_restored']
    assert llm.calls == limit and result['stop_reason'] == 'call_limit'


def test_budget_stop_is_not_retried(setup, monkeypatch):
    job, llm, events = setup
    job['max_calls'] = 4
    sequence(monkeypatch, llm, ['budget_exceeded'])
    result = loop.run_candidate(llm, job, events)
    assert llm.calls == 1 and result['original_restored']


def test_success_stops_early(setup, monkeypatch):
    job, llm, events = setup
    job['max_calls'] = 4
    sequence(monkeypatch, llm, ['completed'])
    monkeypatch.setattr(loop.guarded, 'checked', lambda *args: outcomes(True))
    assert loop.run_candidate(llm, job, events)['published'] and llm.calls == 1


def test_mutated_guard_cannot_publish(setup, monkeypatch):
    job, llm, events = setup
    job['max_calls'] = 4
    sequence(monkeypatch, llm, ['completed'])

    def checked(*args):
        (Path(job['harness']) / 'test_admission.py').write_text('tampered')
        return outcomes(True)

    monkeypatch.setattr(loop.guarded, 'checked', checked)
    result = loop.run_candidate(llm, job, events)
    assert result['status'] == 'agent_error' and result['original_restored'] and not result['published']


def test_feedback_uses_current_round_logs(tmp_path, monkeypatch):
    harness = tmp_path / 'checks'
    harness.mkdir()
    (harness / 'test_admission.py').write_text('public tests')
    paths = []
    monkeypatch.setattr(loop.previous, 'diagnostic', lambda checks, logs, *args: paths.append(logs) or 'failure')
    job = {'harness': str(harness), 'frozen_harness': str(harness)}
    loop.public_feedback(outcomes(False), tmp_path, job, tmp_path, 'round-03')
    assert paths == [tmp_path / 'round-03-public', tmp_path / 'round-03-frozen']
