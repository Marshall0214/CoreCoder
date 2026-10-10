import pytest

from docs.experiments import flag_contract_v1 as contract
from docs.experiments import public_contract_feedback_v1 as guard
from docs.experiments.public_contract_repair_v1 import run, trial_config


def test_contract_has_exact_expected_values_and_compiles(tmp_path):
    harness = contract.write_harness(tmp_path / 'checks')
    text = (harness / 'test_admission.py').read_text()
    compile(text, 'test_admission.py', 'exec')
    assert 'assertNotEqual' not in text
    assert 'repr(str(False))' in text
    assert 'default=False' in text and 'type=str' in text
    with pytest.raises(FileExistsError):
        contract.write_harness(harness)


def test_contract_failure_blocks_publish_even_if_old_public_checks_pass():
    passed = {'Reproduce': {'passed': True}, 'Preserve': {'passed': True}}
    failed = {'Reproduce': {'passed': False}, 'Preserve': {'passed': True}}
    assert not guard.valid({'public': passed, 'frozen': passed})
    assert not guard.valid({'public': passed, 'frozen': passed, 'contract': failed})
    assert guard.valid({'public': passed, 'frozen': passed, 'contract': passed})


def test_runner_preserves_scope_and_budgets(tmp_path):
    with pytest.raises(ValueError, match='Only the envvar failure'):
        run(tmp_path / 'out', 'full')
    c = trial_config('deepseek-high')
    assert (c.token_budget, c.max_output_tokens, c.context_tokens) == (60000, 32768, 65536)
