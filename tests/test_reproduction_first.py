import hashlib
from types import SimpleNamespace

import pytest

from docs.experiments import reproduction_first_feedback_v1 as guard
from docs.experiments.reproduction_first_repair_v1 import run, trial_config
from evals.runner import digest, snapshot
from evals.runtime import Events


@pytest.mark.parametrize('status', ['completed', 'output_truncated', 'corrected', 'failed-correction'])
def test_original_public_evidence_precedes_inference_and_truncation_rolls_back(tmp_path, monkeypatch, status):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'app.py').write_text('def run():\n    return 1\n')
    job = {'workspace': str(workspace), 'description': 'run must return 2', 'allowed_files': ['app.py'],
           'original_hash': digest(snapshot(workspace)),
           'description_hash': hashlib.sha256(b'run must return 2').hexdigest(), 'evidence': []}
    for label in ('harness', 'frozen_harness'):
        folder = tmp_path / label
        folder.mkdir()
        (folder / 'test_admission.py').write_text('PUBLIC_CODE' if label == 'harness' else 'GUARD_CODE')
        job[label], job[label + '_hash'] = str(folder), digest(snapshot(folder))
    order = []
    def checked(workspace, job, root, stage):
        order.append(stage)
        return {label: {group: {'passed': (stage != 'before' or group == 'Preserve')
                               and not (stage == 'initial' and status in {'corrected', 'failed-correction'}),
                               'timed_out': False, 'tests_run': 1}
                       for group in ('Reproduce', 'Preserve')} for label in ('public', 'frozen')}
    monkeypatch.setattr(guard, 'checked', checked)
    monkeypatch.setattr(guard.previous.repair, 'validate_evidence', lambda *a: None)
    monkeypatch.setattr(guard.previous, 'diagnostic', lambda outcomes, logs, *a: 'ACTUAL_PUBLIC_FAILURE')
    monkeypatch.setattr(guard, 'feedback', lambda *a: {'observations': 'CURRENT_PUBLIC_FAILURE'})
    llm = SimpleNamespace(calls=0)
    llm.metrics = lambda: {'llm_calls': llm.calls}
    def request(llm, workspace, job, evidence, root, stage, feedback=None):
        if stage == 'initial':
            assert order == ['before']
            assert feedback['observations'] == 'ACTUAL_PUBLIC_FAILURE'
            assert feedback['test_code'] == 'PUBLIC_CODE'
        else:
            assert order == ['before', 'initial']
            assert feedback['observations'] == 'CURRENT_PUBLIC_FAILURE'
            assert any('return 2' in r['content'] for r in evidence)
        assert 'GUARD_CODE' not in str(feedback)
        llm.calls += 1
        (workspace / 'app.py').write_text('def run():\n    return 2\n')
        returned = ('invalid_patch' if status == 'failed-correction' and stage == 'feedback'
                    else 'completed' if status in {'corrected', 'failed-correction'} else status)
        return {'status': returned}
    monkeypatch.setattr(guard.previous, 'request', request)
    result = guard.run_candidate(llm, job, Events(tmp_path / 'trace.jsonl', 'test'))
    assert result['published'] is (status in {'completed', 'corrected'})
    assert result['original_restored'] is (status not in {'completed', 'corrected'})
    assert llm.calls == (2 if status in {'corrected', 'failed-correction'} else 1)
    assert (tmp_path / 'initial-observation.json').exists()


def test_bad_reproduction_prevents_model_call():
    outcomes = {label: {group: {'passed': True, 'timed_out': False, 'tests_run': 1}
                       for group in ('Reproduce', 'Preserve')} for label in ('public', 'frozen')}
    with pytest.raises(ValueError, match='precondition'):
        guard.initial_observation(outcomes, None, {}, None)


def test_range_only_and_baseline_limits(tmp_path):
    with pytest.raises(ValueError, match='remaining range failure'):
        run(tmp_path / 'output', 'full')
    c = trial_config('deepseek-high')
    assert c.token_budget == 60000 and c.max_output_tokens == 32768
    assert c.context_tokens == 65536 and c.wall_timeout == 1200
