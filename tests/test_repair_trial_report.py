import copy

import pytest

from docs.experiments.repair_trial_report_v1 import audited_rows, compare


def row(task, policy='off', passed=True):
    return {'task_id': task, 'policy': policy, 'accepted': passed,
            'worker': {'status': 'completed' if passed else 'failed_public_validation',
                       'metrics': {'llm_calls': 1, 'budget_accounted_tokens': 100, 'missing_usage_calls': 0}},
            'verification': {'passed': passed},
            'public': {'Reproduce': {'passed': passed}, 'Preserve': {'passed': True}},
            'frozen': {'Reproduce': {'passed': passed}, 'Preserve': {'passed': True}}}


def test_rejects_duplicate_missing_and_running_results():
    r = row('a')
    for report in ({'complete': False, 'runs': [r]},
                   {'complete': True, 'runs': [r, r]},
                   {'complete': True, 'runs': []}):
        with pytest.raises(ValueError):
            audited_rows(report, 'off', {'a'})


def test_rejects_false_acceptance_and_empty_verification():
    for key in ('verification', 'public', 'frozen'):
        r = copy.deepcopy(row('a'))
        if key == 'verification':
            r[key]['passed'] = False
        else:
            r[key] = {}
        with pytest.raises(ValueError, match='contradicts'):
            audited_rows({'complete': True, 'runs': [r]}, 'off', {'a'})


def test_development_success_is_not_full_pool_goal():
    cases = [{'task_id': str(i), 'repo': 'repo', 'split': 'development' if i < 30 else 'heldout',
              'defect_type': 'type'} for i in range(50)]
    history = {'complete': True, 'runs': [row(str(i), 'full', i < 20) for i in range(50)]}
    trial = {'complete': True, 'protocol': {'scope': 'development'},
             'runs': [row(str(i)) for i in range(30)]}
    result = compare({'cases': cases}, history, trial, 'off')
    assert result['candidate_passed'] == 30
    assert result['gained'] == sorted(str(i) for i in range(20, 30))
    assert not result['full_pool_numeric_target_met']
    for case in cases:
        del case['defect_type']
    assert 'defect_type' not in compare({'cases': cases}, history, trial, 'off')['grouped']
