"""Real worker, HTTP lifecycle, SQLite approval and Docker; zero model calls."""
import os

import pytest

pytest.importorskip('fastapi')
pytest.importorskip('langgraph.checkpoint.sqlite')
from fastapi.testclient import TestClient

from repairflow.bundles import read
from repairflow.issue_registry import register
from service.app import create_app
from tests.issue_service_fixture import admitted, responses
from tests.test_service import wait

pytestmark = pytest.mark.skipif(os.environ.get('CORECODER_RUN_DOCKER_TESTS') != '1', reason='Requires pinned local Docker image')


def setup(tmp_path, monkeypatch, succeeds=True):
    prepared, configuration = admitted(tmp_path / 'inputs', os.environ.get('CORECODER_SANDBOX_IMAGE'))
    registry = tmp_path / 'catalog'
    register(prepared, configuration, registry / 'sample', responses=responses(tmp_path / 'responses.json', succeeds),
             observation_policy='compact-v1')
    monkeypatch.setenv('CORECODER_ISSUE_TASKS', str(registry))
    return tmp_path / 'service'


def submit(client):
    response = client.post('/tasks', headers={'Idempotency-Key': 'issue-demo'}, json={
        'suite': 'issues', 'task_id': 'sample', 'mode': 'scripted', 'workflow': 'issue-approval-v1'})
    assert response.status_code == 202, response.text
    return response.json()['id']


def test_new_issue_api_approval_restart_and_reviewable_artifacts(tmp_path, monkeypatch):
    output = setup(tmp_path, monkeypatch)
    with TestClient(create_app(output, timeout=90)) as client:
        assert client.get('/catalog').json()['issues'][0]['task_id'] == 'sample'
        task_id = submit(client)
        assert submit(client) == task_id
        wait(client, task_id, lambda row: row['state'] == 'awaiting_approval', timeout=45)
        assert not (output / task_id / 'runs').exists()
    with TestClient(create_app(output, timeout=90)) as client:
        assert client.get(f'/tasks/{task_id}').json()['state'] == 'awaiting_approval'
        client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'})
        result = wait(client, task_id, timeout=90)
        assert result['state'] == 'ready_for_review', result
        assert not result['result']['accepted'] and result['result']['fresh_model_calls'] == 0
        assert result['result']['public_checks_passed'] and result['result']['requires_review']
        for name in ('report.json', 'patch.diff', 'trace.jsonl', 'actions.json', 'agent-initial-context.json', 'provenance.json',
                     'observability.json'):
            assert client.get(f'/tasks/{task_id}/artifacts/{name}').status_code == 200
        assert client.get(f'/tasks/{task_id}/artifacts/observability.json').json()['status'] == 'disabled'
        assert client.get(f'/tasks/{task_id}/artifacts/responses.json').status_code == 404
        assert 'ready_for_review' in client.get(f'/tasks/{task_id}/events').text
        assert client.get('/tasks').json()[0]['id'] == task_id
        before = read(output / task_id / 'runs/report.json')
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).json()['state'] == 'ready_for_review'
        assert read(output / task_id / 'runs/report.json') == before
        assert read(output / task_id / 'runs/actions.json')[0]['result']['content'] == 'STEP = 2\n'
    from sandbox.runner import control, owner

    assert not control(['ps', '-aq', '--filter', 'label=corecoder.sandbox.owner=' + owner(output / task_id)]).strip()


@pytest.mark.parametrize('action', ['reject', 'cancel'])
def test_new_issue_reject_and_cancel_perform_no_execution(tmp_path, monkeypatch, action):
    output = setup(tmp_path, monkeypatch)
    with TestClient(create_app(output, timeout=90)) as client:
        task_id = submit(client)
        wait(client, task_id, lambda row: row['state'] == 'awaiting_approval', timeout=45)
        if action == 'reject':
            client.post(f'/tasks/{task_id}/approval', json={'decision': 'reject'})
            assert wait(client, task_id, timeout=45)['state'] == 'rejected'
        else:
            assert client.post(f'/tasks/{task_id}/cancel').json()['state'] == 'cancelled'
        assert not (output / task_id / 'execution-started').exists()
        assert not (output / task_id / 'runs').exists()


def test_new_issue_failed_repair_keeps_report_and_empty_patch(tmp_path, monkeypatch):
    output = setup(tmp_path, monkeypatch, succeeds=False)
    with TestClient(create_app(output, timeout=90)) as client:
        task_id = submit(client)
        wait(client, task_id, lambda row: row['state'] == 'awaiting_approval', timeout=45)
        client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'})
        result = wait(client, task_id, timeout=90)
        assert result['state'] == 'failed' and not result['result']['accepted']
        report = client.get(f'/tasks/{task_id}/artifacts/report.json').json()
        assert report['candidate_rolled_back'] and report['fresh_model_calls'] == 0
        assert client.get(f'/tasks/{task_id}/artifacts/patch.diff').text == ''
