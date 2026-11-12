"""Receipt verification must reject missing evidence and leaked source payloads."""
from collections import Counter
from copy import deepcopy

import pytest

from deploy.langfuse.verify import validate


def evidence():
    rows = [{'id': 'root', 'name': 'issue-repair', 'traceId': 'trace', 'parentObservationId': None,
             'endTime': '2026-10-29T00:00:00Z', 'output': {'accepted': False, 'public_checks_passed': True},
             'metadata': {'fresh_model_calls': 0, 'independent_verification_available': False}}]
    for name in ('scripted-response', 'apply_patch', 'docker-public-checks'):
        rows.append({'id': name, 'name': name, 'traceId': 'trace', 'parentObservationId': 'root',
                     'endTime': '2026-10-29T00:00:00Z', 'output': {'Reproduce': {'passed': True}}
                     if name == 'docker-public-checks' else None})
    scores = [{'name': name, 'value': value} for name, value in (
        ('public_checks_passed', True), ('independent_verification_available', False), ('fresh_model_calls', 0))]
    return rows, scores


def test_complete_server_tree_and_scores_are_required():
    rows, scores = evidence()
    original = deepcopy(rows)
    result = validate(rows, scores, 'trace')
    assert result['parent_links_verified'] and result['observation_count'] == 4
    assert rows == original
    assert validate(rows, scores[:-1], 'trace') is None
    assert validate(rows, scores, 'other-trace') is None
    assert validate(rows[1:], scores, 'trace') is None


def test_sdk_logical_root_can_keep_an_external_physical_parent():
    rows, scores = evidence()
    rows[0].update(parentObservationId='external-parent', isRootObservation=True)
    assert validate(rows, scores, 'trace')['parent_links_verified']
    rows[0]['isRootObservation'] = False
    assert validate(rows, scores, 'trace') is None
    rows[0].update(isRootObservation=True, parentObservationId='apply_patch')
    assert validate(rows, scores, 'trace') is None


def test_matching_names_cannot_hide_a_missing_second_operation():
    rows, scores = evidence()
    counts = Counter(row['name'] for row in rows)
    counts['docker-public-checks'] += 1
    assert validate(rows, scores, 'trace', counts) is None
    rows.append(dict(rows[-1], id='second-check'))
    assert validate(rows, scores, 'trace', counts)['observation_count'] == 5


@pytest.mark.parametrize('timed_out', [False, True])
def test_feedback_timeout_summary_is_accepted_without_content_capture(timed_out):
    rows, scores = evidence()
    rows[-1]['output'] = {'Reproduce': {'passed': not timed_out, 'tests_run': 1,
                                      'errors': 0, 'failures': 0, 'timed_out': timed_out},
                          'Preserve': {'passed': True, 'tests_run': 1, 'timed_out': False}}
    assert validate(rows, scores, 'trace')['summary_only_payloads']


@pytest.mark.parametrize('extra', [
    {'timed_out': 'private code'}, {'timed_out': {'content': 'source'}}, {'timed_out': 0},
    {'timed_out': False, 'source': 'private code'}, {'timed_out': False, 'logs': 'raw log'},
])
def test_feedback_timeout_field_cannot_hide_code_or_logs(extra):
    rows, scores = evidence()
    rows[-1]['output'] = {'Reproduce': {'passed': True, **extra}}
    assert validate(rows, scores, 'trace') is None


@pytest.mark.parametrize('index,key,value', [
    (1, 'parentObservationId', 'unrelated'), (1, 'endTime', None),
    (1, 'input', 'private prompt'), (2, 'output', {'content': 'source code'}),
    (3, 'output', {'Reproduce': {'logs': 'raw log'}}),
    (0, 'output', {'accepted': True, 'public_checks_passed': True}),
    (0, 'metadata', {'fresh_model_calls': 1, 'independent_verification_available': False}),
])
def test_invalid_or_content_bearing_server_evidence_is_rejected(index, key, value):
    rows, scores = evidence()
    rows[index][key] = value
    assert validate(rows, scores, 'trace') is None
