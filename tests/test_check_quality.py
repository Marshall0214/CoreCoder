import json

import pytest

from evals.check_quality import collect, diagnose


def outcome(passed, **extra):
    return {'passed': passed, 'returncode': 0 if passed else 1, 'timed_out': False,
            'checks_unchanged': True, 'tests_run': 2, 'assertion_failure': not passed} | extra


def report(original=None, candidate=None, final=None, accepted=True):
    checks = {'generation_status': 'valid', 'review_status': 'valid', 'accepted_tests': ['C.test_a']}
    for key, value in [('original', original), ('candidate', candidate), ('final', final)]:
        if value is not None:
            checks[key] = value
    return {'run_id': 'run-1', 'task_id': 'task', 'accepted': accepted,
            'evaluation_protocol': 'v4', 'fixture_hash': 'fixture',
            'implementation': {'source_hash': 'source'}, 'worker': {'public_checks': checks}}


def test_detection_and_conflict_are_separate_from_correctness():
    row = diagnose(report(outcome(True), outcome(False)))
    assert row['defect_detection'] == 'missed'
    assert row['accepted_patch_conflict'] is True
    assert row['conflict_interpretation'] == 'requires_contract_review'
    assert row['contract_ambiguity'] == 'not_automatically_determined'


def test_final_failure_is_not_hidden_by_successful_candidate():
    row = diagnose(report(outcome(False), outcome(True), outcome(False)))
    assert row['defect_detection'] == 'detected'
    assert row['final_public_pass'] is False and row['accepted_patch_conflict']


@pytest.mark.parametrize('extra', [{'timed_out': True}, {'checks_unchanged': False},
                                 {'tests_run': 0}, {'assertion_failure': False},
                                 {'returncode': 0}, {'tests_run': True}])
def test_invalid_or_error_execution_is_unknown(extra):
    row = diagnose(report(outcome(False, **extra), outcome(False, **extra)))
    assert row['defect_detection'] == 'unknown'
    assert row['final_public_pass'] is None and not row['accepted_patch_conflict']


def test_generation_failure_does_not_count_as_detection():
    row = diagnose(report())
    assert row['defect_detection'] == 'unknown' and row['final_public_pass'] is None


def write_report(root, name, data):
    path = root / name / 'report.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


def test_collection_preserves_provenance_and_groups_versions(tmp_path):
    a = report(outcome(False), outcome(True))
    path = write_report(tmp_path, 'a', a)
    before = path.read_bytes()
    write_report(tmp_path, 'copy', a)
    b = report(outcome(True), outcome(False))
    b.update(run_id='run-2', fixture_hash='v2')
    write_report(tmp_path, 'b', b)
    result = collect(tmp_path)
    assert len(result['runs']) == 2 and len(result['groups']) == 2
    assert path.read_bytes() == before
    assert all(len(row['report_hash']) == 64 for row in result['runs'])


def test_conflicting_duplicate_is_rejected(tmp_path):
    write_report(tmp_path, 'a', report())
    write_report(tmp_path, 'b', report(accepted=False))
    with pytest.raises(ValueError, match='Conflicting duplicate'):
        collect(tmp_path)


def test_missing_checks_are_not_added_to_quality_denominator(tmp_path):
    data = report()
    data['worker'] = {}
    write_report(tmp_path, 'a', data)
    with pytest.raises(ValueError, match='No public-check'):
        collect(tmp_path)
