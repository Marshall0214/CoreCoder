import copy

import pytest

from docs.experiments.reasoning_budget_compare_v1 import POLICIES, trial_config
from docs.experiments.reasoning_budget_report_v1 import compare
from tests.test_repair_trial_report import row


def experiment(high_passed=38):
    cases = [{'task_id': str(i), 'repo': 'repo', 'split': 'development' if i < 30 else 'heldout'} for i in range(50)]
    history = {'complete': True, 'runs': [row(str(i), 'full', i < 32) for i in range(50)]}
    trial = {'complete': True, 'protocol': {'scope': 'full', 'policies': POLICIES,
                                          'tasks': [c['task_id'] for c in cases],
                                          'per_policy_config': {p: trial_config(p).to_dict() for p in POLICIES}}, 'runs': []}
    for p in POLICIES:
        for i in range(50):
            r = row(str(i), p, i < (32 if p == 'deepseek-off' else high_passed))
            r['worker'].update(published=r['accepted'], provider_calls=[
                {'response_received': True, 'total_tokens': 100, 'prompt_hash': str(i)}])
            r['process'] = {'returncode': 0, 'timed_out': False, 'seconds': 1}
            trial['runs'].append(r)
    return {'cases': cases}, history, trial


def test_full_pool_gate_requires_38_verified_successes():
    for passed in (37, 38):
        result = compare(*experiment(passed))
        assert result['full_pool_numeric_target_met'] == (passed >= 38)
        assert result['first_prompts_equal'] == 50
        assert len(result['gained']) == passed - 32


@pytest.mark.parametrize('fault', ['running', 'duplicate', 'prompt', 'budget', 'usage', 'process', 'publication'])
def test_completion_audit_rejects_invalid_evidence(fault):
    manifest, history, trial = experiment()
    trial = copy.deepcopy(trial)
    r = trial['runs'][50]
    if fault == 'running':
        trial['complete'] = False
    elif fault == 'duplicate':
        trial['runs'][-1] = copy.deepcopy(trial['runs'][-2])
    elif fault == 'prompt':
        r['worker']['provider_calls'][0]['prompt_hash'] = 'different'
    elif fault == 'budget':
        trial['protocol']['per_policy_config']['deepseek-high']['token_budget'] += 1
    elif fault == 'usage':
        r['worker']['provider_calls'][0]['total_tokens'] = 99
    elif fault == 'process':
        r['process']['timed_out'] = True
    else:
        r['worker']['published'] = False
    with pytest.raises(ValueError):
        compare(manifest, history, trial)
