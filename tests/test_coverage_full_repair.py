import pytest

from docs.experiments.coverage_full_repair_v1 import run, trial_config


def test_full_coverage_runner_rejects_partial_scope_before_requests(tmp_path):
    with pytest.raises(ValueError, match='all 50 tasks'):
        run(tmp_path / 'out', 'pilot')
    assert not (tmp_path / 'out').exists()


def test_full_coverage_runner_preserves_comparison_budgets():
    config = trial_config('deepseek-high')
    assert config.model == 'deepseek-flash'
    assert config.reasoning_effort == 'high'
    assert (config.token_budget, config.max_output_tokens, config.context_tokens,
            config.wall_timeout) == (60000, 32768, 65536, 1200)
