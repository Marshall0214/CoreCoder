import json

import pytest

from evals.check_surface import caller_state_tests, filter_surface_checks
from evals.fixed_evidence import generate_patch
from evals.runtime import Events
from tests.test_contract_catalog import review
from tests.test_contract_feedback import CODE, RecordingLLM, patch, setup_run


def check_code(assertion, extra=''):
    return ('import unittest\nfrom projector import apply_batch\n'
            'class Checks(unittest.TestCase):\n'
            '    def test_behavior(self):\n'
            '        state, seen = {}, set()\n'
            '        result = apply_batch(state, seen, [])\n'
            + ''.join('        ' + line + '\n' for line in extra.splitlines())
            + '        ' + assertion + '\n')


@pytest.mark.parametrize('assertion,extra', [
    ("self.assertIn('e1', seen)", ''),
    ("self.assertNotIn('e1', alias)", 'alias = seen'),
    ("self.assertEqual(copy, set())", 'alias = seen\ncopy = alias'),
    ("self.assertEqual(state['tenant'], 1)", ''),
    ("self.assertTrue(seen)", ''),
])
def test_input_representation_and_aliases_are_excluded(assertion, extra):
    rejected = caller_state_tests(check_code(assertion, extra))
    assert list(rejected) == ['Checks.test_behavior']


@pytest.mark.parametrize('assertion', [
    "self.assertEqual(result, {'tenant': 1})",
    "self.assertEqual(len(result), 1)",
    "self.assertIn('tenant', result)",
])
def test_return_values_remain_observable(assertion):
    assert caller_state_tests(check_code(assertion)) == {}


def test_keyword_arguments_and_import_alias_are_tracked():
    code = check_code("self.assertIn('e1', seen)").replace(
        'import apply_batch', 'import apply_batch as replay').replace(
        'apply_batch(state, seen, [])', 'replay(state=state, seen=seen, records=[])')
    assert caller_state_tests(code)['Checks.test_behavior'] == ['seen']


def test_entire_test_is_removed_and_model_acceptance_preserved():
    code = check_code("self.assertIn('e1', seen)")
    reviews = [{'test': 'Checks.test_behavior', 'verdict': 'accept'}]
    filtered, rejected = filter_surface_checks(code, reviews)
    assert filtered is None and rejected
    assert reviews[0]['model_verdict'] == 'accept' and reviews[0]['verdict'] == 'reject'


def test_new_policy_runs_schema_review_without_changing_patch_or_import_rules(tmp_path):
    result, llm, _ = setup_run(tmp_path, [{'code': CODE}, {'reviews': [review()]},
                                        patch('return 1', 'return 3')],
                              public_check_policy='contract-surface')
    assert result['protocol'] == 'public-contract-feedback-v5-surface'
    assert result['public_checks']['candidate']['passed']
    assert result['public_checks']['surface_rejected_tests'] == {}
    assert result['public_checks']['semantic_correctness_verified'] is False
    assert llm.options[1]['response_format']['type'] == 'json_schema'
    assert 'plain Python class' in llm.messages[0][0]['content']


def test_disallowed_helper_import_remains_rejected(tmp_path):
    invalid = 'from dataclasses import dataclass\n' + CODE
    result, llm, _ = setup_run(tmp_path, [{'code': invalid}, {'edits': []}],
                              public_check_policy='contract-surface')
    assert result['public_checks']['generation_status'] == 'invalid'
    assert result['feedback_attempts'] == 0 and len(llm.messages) == 2


@pytest.mark.parametrize('feedback', [None, {'stderr': 'public assertion failed'}])
def test_new_protocol_allows_coverage_patch_and_feedback(tmp_path, feedback):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    result = generate_patch(RecordingLLM([{'coverage': [], 'edits': []}]), workspace,
                            'Public behavior', [], Events(tmp_path / 'trace.jsonl', 'test'), [],
                            protocol='public-contract-feedback-v5-surface',
                            policy='contract-coverage', feedback=feedback)
    assert result['status'] == 'completed'


def test_frozen_event_checks_expose_representation_errors():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / '.tmp/evals/localization-workflow-comparison-v1'
    if not root.exists():
        pytest.skip('Local experiment artifacts are not shipped with the repository')
    comparison = json.loads((root / 'comparison.json').read_text(encoding='utf-8'))
    run_id = next(name for name in comparison['run_ids']['schema-feedback'] if name.startswith('event-replay-1-'))
    code = (root / 'schema-feedback' / run_id / 'public-contract-checks.py').read_text(encoding='utf-8')
    rejected = caller_state_tests(code)
    assert 'TestEventProjection.test_single_tenant_increment' in rejected
    assert 'TestEventProjection.test_event_id_with_punctuation' in rejected
