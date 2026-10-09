from pathlib import Path

from docs.experiments import selected_source_repair_v1 as loop
from tests.test_frozen_feedback import outcomes

pytest_plugins = ['tests.test_frozen_feedback']


def test_selection_failure_restores_original_without_patch(setup, monkeypatch):
    job, llm, events = setup
    job.update(policy='model-selected', max_calls=2)

    def invalid(*args):
        llm.calls += 1
        raise ValueError('invalid ID')

    monkeypatch.setattr(loop.selection, 'select', invalid)
    monkeypatch.setattr(loop.previous, 'request', lambda *args: (_ for _ in ()).throw(AssertionError('No patch expected')))
    result = loop.run_candidate(llm, job, events)
    assert result['status'] == 'agent_error' and result['original_restored']
    assert not result['published'] and llm.calls == 1


def test_selected_symbols_are_refreshed_after_public_failure(setup, monkeypatch):
    job, llm, events = setup
    job.update(policy='model-selected', max_calls=2)
    selected = [{'path': 'code.py', 'symbol': 'chosen', 'start_line': 1, 'end_line': 1}]
    refreshed = [{'path': 'code.py', 'symbol': 'chosen', 'start_line': 2, 'end_line': 2}]
    monkeypatch.setattr(loop.selection, 'select', lambda *args: selected)
    seen = []

    def refresh(workspace, allowed, seeds):
        assert seeds == selected
        return refreshed

    def request(shared, workspace, job, evidence, root, stage, feedback=None):
        llm.calls += 1
        seen.append(evidence)
        (workspace / 'code.py').write_text(stage)
        return {'status': 'completed'}

    monkeypatch.setattr(loop.selection, 'refresh', refresh)
    monkeypatch.setattr(loop.previous, 'request', request)
    monkeypatch.setattr(loop, 'public_feedback', lambda *args: {'observations': 'current failure'})
    monkeypatch.setattr(loop.guarded, 'checked', lambda *args: outcomes(llm.calls == 2))
    result = loop.run_candidate(llm, job, events)
    assert seen == [selected, refreshed] and result['published']
    assert (Path(job['workspace']) / 'code.py').read_text() == 'round-02'
