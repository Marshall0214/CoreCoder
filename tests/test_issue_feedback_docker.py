"""Opt-in real CLI/API feedback execution, lifecycle and cleanup; no inference."""
import os
import time
import uuid

import pytest

pytest.importorskip('fastapi')
pytest.importorskip('langgraph.checkpoint.sqlite')
from fastapi.testclient import TestClient

from repairflow.bundles import read
from repairflow.issue_demo import run as demo
from repairflow.issue_registry import register
from sandbox import runner
from tests.issue_service_fixture import admitted, delayed_feedback_harness, feedback_responses
from tests.test_service import wait

pytestmark = pytest.mark.skipif(os.environ.get('CORECODER_RUN_DOCKER_TESTS') != '1',
                                reason='Opt in with an existing local Docker sandbox image')


def setup(tmp_path, monkeypatch, *, succeeds=True, slow=False, profile=None):
    kwargs = {'harness': delayed_feedback_harness()} if slow else {}
    prepared, configuration = admitted(tmp_path / 'inputs', os.environ.get('CORECODER_SANDBOX_IMAGE'), **kwargs)
    root = tmp_path / 'catalog'
    entry = register(prepared, configuration, root / 'sample', engine='feedback-actions-v2',
                     execution_profile=profile,
                     responses=feedback_responses(tmp_path / 'responses.json', succeeds=succeeds))
    monkeypatch.setenv('CORECODER_ISSUE_TASKS', str(root))
    monkeypatch.setenv('CORECODER_LANGFUSE_ENABLED', '0')
    return entry


def submit(client):
    response = client.post('/tasks', headers={'Idempotency-Key': 'feedback-closeout'}, json={
        'suite': 'issues', 'task_id': 'sample', 'mode': 'scripted', 'workflow': 'issue-approval-v1'})
    assert response.status_code == 202, response.text
    return response.json()['id']


def test_recorded_feedback_demo_runs_cli_and_api_with_the_same_reviewable_patch(tmp_path, monkeypatch):
    entry = setup(tmp_path, monkeypatch)
    # Task admission owns the image; a worker's ambient default must not replace it.
    monkeypatch.setenv('CORECODER_SANDBOX_IMAGE', 'corecoder-closeout-wrong-image:must-not-be-used')
    result = demo(entry, tmp_path / 'demo')
    assert result['status'] == 'passed' and result['complete_feedback_cycle']
    assert result['fresh_model_calls'] == 0 and not result['independent_acceptance']
    assert result['api_state'] == 'ready_for_review'
    assert result['same_patch'] and result['approval_restart'] and result['idempotent_submission']
    assert result['repeated_approval_no_execution'] and result['rejection_no_execution']
    assert result['feedback_counts']['requests'] == 5
    assert result['feedback_counts']['reads'] == 3 and result['feedback_counts']['applied_patches'] == 2
    assert result['feedback_counts']['public_validations'] == 3
    assert [row['Reproduce'] for row in result['public_validation_sequence']] == [False, False, True]
    delivered = read(tmp_path / 'demo/evidence/report.json')
    assert not delivered['accepted'] and delivered['public_checks_passed']
    assert delivered['original_unchanged'] and delivered['requires_review']
    assert (tmp_path / 'demo/evidence/context-selection.json').is_file()


def test_unresolved_feedback_is_failed_and_keeps_the_report_and_candidate(tmp_path, monkeypatch):
    from service.app import create_app

    setup(tmp_path, monkeypatch, succeeds=False)
    with TestClient(create_app(tmp_path / 'service', timeout=2520)) as client:
        task_id = submit(client)
        wait(client, task_id, lambda row: row['state'] == 'awaiting_approval', timeout=45)
        client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).raise_for_status()
        result = wait(client, task_id, timeout=90)
        assert result['state'] == 'failed' and not result['result']['accepted']
        response = client.get(f'/tasks/{task_id}/artifacts/report.json')
        assert response.status_code == 200
        report = response.json()
        assert not report['public_checks_passed'] and report['fresh_model_calls'] == 0
        assert report['original_unchanged']
        assert client.get(f'/tasks/{task_id}/artifacts/patch.diff').text == ''
        assert client.get(f'/tasks/{task_id}/artifacts/responses.json').status_code == 404


def wait_for_owned_container(client, task_id, service, timeout=45):
    owned = 'label=corecoder.sandbox.owner=' + runner.owner(service / task_id)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(f'/tasks/{task_id}').json()['state']
        assert state == 'running', state
        if runner.control(['ps', '-q', '--filter', owned], timeout=5).strip():
            return owned
        time.sleep(0.1)
    raise AssertionError('Execution did not reach an owned running sandbox')


def assert_owned_containers_removed(owned):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not runner.control(['ps', '-aq', '--filter', owned], timeout=5).strip():
            return
        time.sleep(0.1)
    pytest.fail('Terminal task retained its owned sandbox containers')


def test_running_cancel_cleans_only_its_containers_and_delivers_partial_evidence(tmp_path, monkeypatch):
    from service.app import create_app

    setup(tmp_path, monkeypatch, slow=True)
    service = tmp_path / 'service'
    policy = runner.preflight()
    sentinel = runner.control(['run', '-d', '--network', 'none', '--read-only', '--user', '65534:65534',
                               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--memory', '64m',
                               '--pids-limit', '16', '--name', 'corecoder-closeout-' + uuid.uuid4().hex[:12],
                               policy['image_id'], 'python', '-B', '-c', 'import time; time.sleep(120)']).decode().strip()
    assert sentinel
    try:
        with TestClient(create_app(service, timeout=2520)) as client:
            task_id = submit(client)
            wait(client, task_id, lambda row: row['state'] == 'awaiting_approval', timeout=45)
            client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).raise_for_status()
            wait(client, task_id, lambda row: row['state'] == 'running', timeout=45)
            owned = wait_for_owned_container(client, task_id, service)
            client.post(f'/tasks/{task_id}/cancel').raise_for_status()
            result = wait(client, task_id, timeout=45)
            assert result['state'] == 'cancelled' and not result['result']['accepted']
            assert_owned_containers_removed(owned)
            report = client.get(f'/tasks/{task_id}/artifacts/report.json')
            assert report.status_code == 200, report.text
            assert not report.json()['accepted'] and report.json()['fresh_model_calls'] == 0
            assert client.get(f'/tasks/{task_id}/artifacts/patch.diff').status_code == 200
            assert runner.control(['inspect', sentinel, '--format', '{{.State.Running}}']).strip() == b'true'
    finally:
        runner.control(['rm', '-f', sentinel], timeout=10)


def test_feedback_deadline_is_timed_out_with_partial_report(tmp_path, monkeypatch):
    from service.app import create_app

    profile = {'exploration_requests': 20, 'feedback_requests': 20, 'exploration_seconds': 30,
               'feedback_seconds': 1, 'context_target_tokens': 12000}
    setup(tmp_path, monkeypatch, slow=True, profile=profile)
    service = tmp_path / 'service'
    with TestClient(create_app(service, timeout=151)) as client:
        task_id = submit(client)
        wait(client, task_id, lambda row: row['state'] == 'awaiting_approval', timeout=45)
        client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).raise_for_status()
        result = wait(client, task_id, timeout=45)
        assert result['state'] == 'timed_out', result
        report = client.get(f'/tasks/{task_id}/artifacts/report.json')
        assert report.status_code == 200, report.text
        assert not report.json()['accepted'] and report.json()['fresh_model_calls'] == 0
        assert_owned_containers_removed('label=corecoder.sandbox.owner=' + runner.owner(service / task_id))
