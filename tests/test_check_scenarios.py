import json
import shutil

import pytest

from evals.check_surface import caller_state_tests
from evals.contract_feedback import check_candidate, validate_checks
from evals.fixed_evidence import generate_patch
from evals.runner import DEFAULT_SUITE
from evals.runtime import Events
from evals.schema import RunConfig, load_suite
from tests.test_contract_catalog import review
from tests.test_contract_feedback import CODE, RecordingLLM, patch, setup_run

# Derived from the public events.md only; never sent as model examples.
PUBLIC_CHECKS = '''import unittest
from gateway import replay_batch
class PublicEvents(unittest.TestCase):
    def test_cross_tenant_same_id(self):
        result = replay_batch({}, set(), [
            {'tenant': 'red', 'event_id': 'same', 'delta': 2},
            {'tenant': 'blue', 'event_id': 'same', 'delta': 3}])
        self.assertEqual(result, {'red': 2, 'blue': 3})
    def test_duplicate_before_later_record(self):
        result = replay_batch({}, set(), [
            {'tenant': 'red', 'event_id': 'first', 'delta': 2},
            {'tenant': 'red', 'event_id': 'first', 'delta': 20},
            {'tenant': 'red', 'event_id': 'later', 'delta': 5}])
        self.assertEqual(result, {'red': 7})
    def test_replay_across_calls(self):
        state, seen = {}, set()
        first = dict(replay_batch(state, seen, [
            {'tenant': 'red', 'event_id': 'first', 'delta': 2}]))
        second = dict(replay_batch(state, seen, [
            {'tenant': 'red', 'event_id': 'first', 'delta': 20},
            {'tenant': 'red', 'event_id': 'later', 'delta': 5}]))
        self.assertEqual(first, {'red': 2})
        self.assertEqual(second, {'red': 7})
'''

CORRECT = '''def apply_batch(state, seen, records):
    for event in records:
        identity = (event['tenant'], event['event_id'])
        if identity in seen:
            continue
        tenant = event['tenant']
        state[tenant] = state.get(tenant, 0) + event['delta']
        seen.add(identity)
    return state
'''


@pytest.mark.parametrize('variant,failures', [('original', 3), ('correct', 0),
                                            ('global-id', 1), ('early-stop', 2)])
def test_public_scenarios_distinguish_each_behavior(tmp_path, variant, failures):
    task = load_suite(DEFAULT_SUITE / 'localization-v1', ['event-replay'])[0]
    workspace = tmp_path / 'workspace'
    shutil.copytree(task.root / 'workspace', workspace)
    if variant != 'original':
        source = CORRECT
        if variant == 'global-id':
            source = source.replace("(event['tenant'], event['event_id'])", "event['event_id']")
        if variant == 'early-stop':
            source = source.replace('            continue', '            return state')
        (workspace / 'projector.py').write_text(source, encoding='utf-8')
    assert validate_checks(json.dumps({'code': PUBLIC_CHECKS}), task.allowed_files) == PUBLIC_CHECKS
    assert caller_state_tests(PUBLIC_CHECKS) == {}
    outcome, _ = check_candidate(workspace, PUBLIC_CHECKS, RunConfig(),
                                 Events(tmp_path / 'trace.jsonl', 'test'), variant)
    assert outcome['tests_run'] == 3 and outcome['passed'] is (failures == 0)
    stderr = (tmp_path / outcome['stderr']).read_text(encoding='utf-8')
    assert stderr.count('\nFAIL: ') == failures
    assert '\nERROR: ' not in stderr


def test_new_policy_preserves_review_and_initial_patch(tmp_path):
    result, llm, _ = setup_run(tmp_path, [{'code': CODE}, {'reviews': [review()]},
                                        patch('return 1', 'return 3')],
                              public_check_policy='contract-scenarios')
    assert result['protocol'] == 'public-contract-feedback-v6-scenarios'
    assert result['public_checks']['candidate']['passed']
    assert result['public_checks']['surface_rejected_tests'] == {}
    assert llm.options[1]['response_format']['type'] == 'json_schema'
    assert 'reuse exactly the same identifier' in llm.messages[0][0]['content']
    assert PUBLIC_CHECKS not in json.dumps(llm.messages)


@pytest.mark.parametrize('feedback', [None, {'stderr': 'public assertion failed'}])
def test_scenario_protocol_supports_coverage_and_feedback(tmp_path, feedback):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    result = generate_patch(RecordingLLM([{'coverage': [], 'edits': []}]), workspace,
                            'Public behavior', [], Events(tmp_path / 'trace.jsonl', 'test'), [],
                            protocol='public-contract-feedback-v6-scenarios',
                            policy='contract-coverage', feedback=feedback)
    assert result['status'] == 'completed'
