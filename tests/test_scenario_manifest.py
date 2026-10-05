import json

import pytest

from evals.scenario_manifest import KINDS, diagnose, parse_manifest, response_format
from tests.test_check_scenarios import PUBLIC_CHECKS
from tests.test_contract_catalog import review
from tests.test_contract_feedback import CODE, patch, setup_run

CATALOG = [{'id': 'c0001', 'source': 'description', 'line': 1, 'text': 'Public behavior'}]


def rows():
    return [{'kind': kind, 'status': 'implemented', 'test': f'PublicEvents.{method}',
             'contract_ids': ['c0001'], 'identifier_field': 'event_id', 'scope_field': 'tenant',
             'reason': 'Derived from public contract'} for kind, method in zip(KINDS, [
                 'test_cross_tenant_same_id', 'test_duplicate_before_later_record', 'test_replay_across_calls'])]


def test_public_examples_have_all_three_shapes():
    result = diagnose(PUBLIC_CHECKS, rows())
    assert [r['observation'] for r in result] == ['shape-observed'] * 3
    assert all(r['semantic_correctness_verified'] is False for r in result)


def test_different_ids_do_not_establish_scoped_identity():
    code = PUBLIC_CHECKS.replace("'blue', 'event_id': 'same'", "'blue', 'event_id': 'other'")
    assert diagnose(code, rows())[0]['observation'] == 'shape-missing'


def test_duplicate_at_end_is_not_duplicate_before_new():
    code = PUBLIC_CHECKS.replace("'event_id': 'later', 'delta': 5", "'event_id': 'first', 'delta': 5")
    assert diagnose(code, rows())[1]['observation'] == 'shape-missing'


def test_missing_snapshots_do_not_establish_persistent_replay():
    code = PUBLIC_CHECKS.replace('dict(replay_batch', 'list(replay_batch').replace(
        "self.assertEqual(second, {'red': 7})", "self.assertEqual(first, {'red': 2})")
    assert diagnose(code, rows())[2]['observation'] == 'shape-missing'


def test_unrelated_literal_records_do_not_establish_api_scenario():
    code = PUBLIC_CHECKS.replace('replay_batch({}, set(), [', 'list([')
    assert diagnose(code, rows())[0]['observation'] == 'unknown'


def test_review_filtered_methods_are_reported():
    assert diagnose(None, rows())[0]['observation'] == 'method-missing-or-filtered'


@pytest.mark.parametrize('reset,expected', [('', 'shape-observed'),
                                          ('state, seen = {}, set()', 'shape-missing'),
                                          ('state = {}\n        seen = set()', 'shape-missing')])
def test_shared_identity_across_calls_tracks_simple_rebinding(reset, expected):
    code = '''from gateway import replay_batch
class PublicEvents:
    def test_cross_tenant_same_id(self):
        state = {}
        seen = set()
        first = replay_batch(state, seen, [{'tenant': 'a', 'event_id': 'id'}])
        RESET
        second = replay_batch(state, seen, [{'tenant': 'b', 'event_id': 'id'}])
'''.replace('RESET', reset or 'pass')
    assert diagnose(code, rows())[0]['observation'] == expected


@pytest.mark.parametrize('change', ['unknown-id', 'duplicate-kind', 'missing-source', 'wrong-type', 'extra-field'])
def test_invalid_manifests_are_rejected(change):
    data = rows()
    if change == 'unknown-id':
        data[0]['contract_ids'] = ['hidden']
    elif change == 'duplicate-kind':
        data[1]['kind'] = data[0]['kind']
    elif change == 'missing-source':
        data[0]['contract_ids'] = []
    elif change == 'wrong-type':
        data[0]['scope_field'] = None
    else:
        data[0]['answer'] = 'reference'
    with pytest.raises(ValueError):
        parse_manifest(json.dumps({'code': PUBLIC_CHECKS, 'scenarios': data}), CATALOG)


def test_omissions_are_explicit_and_schema_requires_all_fields():
    data = rows()
    data[0].update(status='omitted', test='', contract_ids=[], reason='Contract does not establish this behavior')
    code, parsed = parse_manifest(json.dumps({'code': PUBLIC_CHECKS, 'scenarios': data}), CATALOG)
    assert diagnose(code, parsed)[0]['observation'] == 'declared-omitted'
    schema = response_format(CATALOG)['json_schema']['schema']
    assert set(schema['required']) == {'code', 'scenarios'}


def test_new_policy_applies_schema_to_generation_and_review(tmp_path):
    data = rows()
    for row in data:
        row.update(status='omitted', test='', contract_ids=[], reason='No matching contract')
    result, llm, _ = setup_run(tmp_path, [{'code': CODE, 'scenarios': data}, {'reviews': [review()]},
                                        patch('return 1', 'return 3')],
                              public_check_policy='contract-manifest')
    assert result['protocol'] == 'public-contract-feedback-v7-manifest'
    assert [bool(options) for options in llm.options] == [True, True, False]
    assert result['public_checks']['candidate']['passed']
    assert len(result['public_checks']['retained_scenario_diagnostics']) == 3
    assert (tmp_path / 'public-check-generation-format.json').exists()
