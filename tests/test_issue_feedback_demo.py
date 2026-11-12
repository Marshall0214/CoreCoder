"""Recording demo contracts without services, containers, or inference."""
import json

import pytest

from repairflow.bundles import read, write
from repairflow.issue_demo import execution_options, feedback_evidence
from tests.issue_service_fixture import delayed_feedback_harness, feedback_responses


def test_demo_selects_only_the_trusted_optional_engine_profile():
    legacy = {'model': 'qwen3.5:27b', 'observation_policy': 'compact-v1'}
    assert execution_options(legacy) == {'mode': 'scripted', 'model': 'qwen3.5:27b',
                                         'workflow': 'symbol-recovery-v1', 'observation_policy': 'compact-v1'}
    profile = {'exploration_requests': 20, 'feedback_requests': 20, 'exploration_seconds': 1200,
               'feedback_seconds': 1200, 'context_target_tokens': 12000}
    options = execution_options({**legacy, 'engine': 'feedback-actions-v2', 'execution_profile': profile})
    assert options['workflow'] == 'feedback-actions-v2' and options['execution_profile'] == profile


def test_recorded_schedule_preserves_revision_and_dependency_read_contract(tmp_path):
    rows = [json.loads(value) for value in read(feedback_responses(tmp_path / 'responses.json'))]
    assert [row['action'] for row in rows] == ['finish', 'read_symbol', 'apply_patch', 'read_symbol',
                                              'read_symbol', 'apply_patch']
    assert rows[2]['arguments']['workspace_revision'] == 0
    assert rows[-1]['arguments']['workspace_revision'] == 1
    assert rows[3]['arguments']['path'] == 'src/pkg/dependency.py'
    assert [json.loads(value)['action'] for value in read(feedback_responses(tmp_path / 'failed.json', succeeds=False))] == [
        'finish', 'finish']


def receipts(tmp_path, *, model_calls=0, independent=False):
    root = tmp_path / 'demo'
    attempts = []
    for number, passed in enumerate((False, False, True)):
        folder = root / 'feedback' / f'validation-{number}'
        folder.mkdir(parents=True)
        write(folder / 'report.json', {'model_calls': model_calls, 'independent_grading_used': independent,
                                      'public_checks': {'Reproduce': {'passed': passed}, 'Preserve': {'passed': True}}})
        attempts.append({'folder': str(folder), 'public_checks_completed': True})
    write(root / 'feedback/report.json', {'validation_attempts': attempts,
                                        'counts': {'applied_patches': 2, 'requests': 5}})
    return root


def test_demo_verifies_real_public_outcomes_instead_of_merely_counting_edits(tmp_path):
    root = receipts(tmp_path)
    result = feedback_evidence(root)
    assert result['complete_feedback_cycle']
    assert [row['Reproduce'] for row in result['public_validation_sequence']] == [False, False, True]
    bad = read(root / 'feedback/validation-2/report.json')
    bad['public_checks']['Reproduce']['passed'] = False
    write(root / 'feedback/validation-2/report.json', bad)
    assert not feedback_evidence(root)['complete_feedback_cycle']


@pytest.mark.parametrize(('model_calls', 'independent'), [(1, False), (0, True)])
def test_recorded_demo_refuses_inference_or_independent_grading_receipts(tmp_path, model_calls, independent):
    root = receipts(tmp_path, model_calls=model_calls, independent=independent)
    with pytest.raises(ValueError, match='model or independent'):
        feedback_evidence(root)


def test_demo_refuses_validation_receipt_outside_its_artifact_root(tmp_path):
    root = receipts(tmp_path)
    report = read(root / 'feedback/report.json')
    report['validation_attempts'][0]['folder'] = str(tmp_path / 'outside')
    write(root / 'feedback/report.json', report)
    with pytest.raises(ValueError, match='outside'):
        feedback_evidence(root)


def test_delayed_fixture_is_valid_python_without_delaying_admission():
    text = delayed_feedback_harness(60)
    compile(text, 'test_admission.py', 'exec')
    assert '"workspace" in' in text and '.sleep(60)' in text
