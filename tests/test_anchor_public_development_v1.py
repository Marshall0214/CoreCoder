import json

import pytest

from docs.experiments import anchor_public_development_v1 as experiment


def rows(accepted=True):
    return [{'task_id': f'task-{i}', 'policy': policy, 'accepted': accepted,
             'verification': {'groups': {'Controls': {'passed': True}}}}
            for i in range(30) for policy in experiment.STRATEGIES]


def workers(eligible=False):
    return [{'task_id': f'task-{i}', 'eligible': eligible} for i in range(30)]


def test_zero_trigger_stops_even_if_all_repairs_pass():
    result = experiment.paired(rows(), workers())
    assert result['complete_pairs'] == 30
    assert result['eligible_count'] == 0 and not result['gate_passed']
    assert result['decision'] == 'no_trigger_coverage_stop_rollout'


def test_incomplete_pairs_never_pass_gate():
    data = rows(False)
    for row in data:
        row['accepted'] = row['policy'] == 'anchor-public'
    result = experiment.paired(data[:-1], workers(True))
    assert result['decision'] == 'incomplete' and not result['gate_passed']


def test_required_net_gain_and_no_control_regressions():
    data = rows(False)
    data[1]['accepted'] = data[3]['accepted'] = True
    result = experiment.paired(data, workers(True))
    assert result['gate_passed'] and result['gained'] == ['task-0', 'task-1']
    data[3]['verification']['groups']['Controls']['passed'] = False
    result = experiment.paired(data, workers(True))
    assert not result['gate_passed'] and result['new_control_failures'] == ['task-1']


def test_one_gain_and_one_loss_are_not_improvement():
    data = rows(False)
    data[1]['accepted'] = data[2]['accepted'] = True
    result = experiment.paired(data, workers(True))
    assert result['gained'] == ['task-0'] and result['lost'] == ['task-1']
    assert not result['gate_passed']


def test_duplicate_strategy_row_is_rejected():
    data = rows()
    with pytest.raises(ValueError, match='Duplicate'):
        experiment.paired(data + [data[0]], workers())


def test_development_selection_cannot_include_heldout(tmp_path):
    cases = [{'task_id': t, 'split': 'development'} for t in experiment.policy.examples.CASES]
    cases += [{'task_id': 'more-split-empty', 'split': 'heldout'}]
    path = tmp_path / 'admission.json'
    path.write_text(json.dumps({'complete': True, 'cases': cases}))
    selected = experiment.development(path)
    assert len(selected) == 30 and all(c['split'] == 'development' for c in selected)
    cases[0]['split'] = 'heldout'
    path.write_text(json.dumps({'complete': True, 'cases': cases}))
    with pytest.raises(ValueError, match='30 fixed'):
        experiment.development(path)
