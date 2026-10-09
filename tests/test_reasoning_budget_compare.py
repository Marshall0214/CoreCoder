import pytest

from docs.experiments.reasoning_budget_compare_v1 import trial_config


def test_paired_configs_have_equal_budgets_and_explicit_efforts():
    off, high = trial_config('deepseek-off').to_dict(), trial_config('deepseek-high').to_dict()
    assert off.pop('reasoning_effort') == 'none'
    assert high.pop('reasoning_effort') == 'high'
    assert off == high
    assert off['token_budget'] == 60000 and off['max_output_tokens'] == 32768
    assert off['context_tokens'] == 65536 and off['wall_timeout'] == 1200


def test_unknown_policy_cannot_silently_choose_non_thinking():
    with pytest.raises(ValueError, match='Unknown thinking policy'):
        trial_config('deepseek-hihg')
