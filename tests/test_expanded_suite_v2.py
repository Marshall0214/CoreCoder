import json

import pytest

from docs.experiments import expanded_admission_v2 as admission
from docs.experiments import failure_classification_v1 as classification


def sample(worker='completed', target=False, controls=True, accepted=False):
    return {'worker': {'status': worker}, 'accepted': accepted,
            'verification': {'passed': accepted, 'scope_violations': [],
                             'groups': {name: {'passed': passed, 'tests_run': 1, 'timed_out': False}
                                        for name, passed in [('Target', target), ('Controls', controls)]}}}


@pytest.mark.parametrize('worker,target,controls,accepted,expected', [
    ('completed', True, True, True, 'passed'),
    ('completed', False, True, False, 'target_failed'),
    ('completed', True, False, False, 'control_regression'),
    ('completed', False, False, False, 'control_regression'),
    ('invalid_patch', True, True, False, 'invalid_patch'),
    ('budget_exceeded', False, True, False, 'budget_stop'),
    ('agent_error', False, True, False, 'execution_fault'),
])
def test_outcomes_respect_worker_and_independent_controls(worker, target, controls, accepted, expected):
    row = classification.classify(sample(worker, target, controls, accepted))
    assert row['outcome'] == expected
    assert row['root_cause'] == (None if expected == 'passed' else 'not_established')


def test_catalog_unique_pinned_and_no_feature_only_tasks():
    catalog = json.loads((admission.DATA / 'new-candidates.json').read_text())['cases']
    assert len(catalog) == len({c['task_id'] for c in catalog}) == 20
    assert not {c['task_id'] for c in catalog}.intersection(classification.LEGACY_TYPES)
    assert sum(c['split'] == 'heldout' for c in catalog) == 10
    for case in catalog:
        assert len(case['before_commit']) == len(case['after_commit']) == 40
        code = (admission.DATA / 'checks' / case['task_id'] / 'test_admission.py').read_text()
        compile(code, case['task_id'], 'exec')
        assert 'class Target' in code and 'class Controls' in code
        assert case['defect_type']


def test_incomplete_base_stops_before_download(tmp_path):
    base = tmp_path / 'base.json'
    base.write_text(json.dumps({'complete': False, 'cases': []}))
    with pytest.raises(ValueError, match='certified'):
        admission.run(base, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_missing_result_cannot_be_summarized():
    with pytest.raises(ValueError, match='every unique task'):
        classification.report([{'task_id': 'missing'}], [])


def test_missing_grading_and_scope_not_reported_as_model_reasoning():
    assert classification.classify(sample('output_truncated'))['outcome'] == 'output_truncated'
    run = sample()
    run['verification']['groups'] = {}
    assert classification.classify(run)['outcome'] == 'grading_fault'
    run['verification']['scope_violations'] = ['private_test.py']
    assert classification.classify(run)['outcome'] == 'scope_violation'
