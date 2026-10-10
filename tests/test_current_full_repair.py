import pytest

from docs.experiments import current_full_feedback_v1 as router
from docs.experiments.current_full_repair_v1 import run, trial_config


def test_contract_is_required_only_for_envvar_task(monkeypatch):
    monkeypatch.setattr(router.standard, 'run_candidate', lambda *args: 'standard')
    monkeypatch.setattr(router.contract, 'run_candidate', lambda *args: 'contract')
    assert router.run_candidate(None, {'task_id': 'other'}, None) == 'standard'
    assert router.run_candidate(None, {'task_id': 'click-flag-envvar', 'contract_harness': 'path'}, None) == 'contract'
    with pytest.raises(ValueError, match='requires versioned'):
        router.run_candidate(None, {'task_id': 'click-flag-envvar'}, None)
    with pytest.raises(ValueError, match='unrelated'):
        router.run_candidate(None, {'task_id': 'other', 'contract_harness': 'path'}, None)


def test_full_runner_keeps_original_limits_and_refuses_partial_scope(tmp_path):
    with pytest.raises(ValueError, match='all 50 tasks'):
        run(tmp_path / 'out', 'pilot')
    c = trial_config('deepseek-high')
    assert (c.token_budget, c.max_output_tokens, c.context_tokens, c.wall_timeout) == (60000, 32768, 65536, 1200)
    assert not (tmp_path / 'out').exists()
