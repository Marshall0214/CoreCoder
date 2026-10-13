import pytest

pytest.importorskip('langgraph.checkpoint.sqlite')
pytest.importorskip('fastapi')
from fastapi.testclient import TestClient

from service.app import create_app
from tests.repair_bundle_fixture import bundle
from tests.test_service import wait


@pytest.fixture(autouse=True)
def explicit_development_backend(monkeypatch):
    monkeypatch.setenv('CORECODER_TEST_BACKEND', 'local')


def submit(client):
    response = client.post('/tasks', headers={'Idempotency-Key': 'repair-demo'}, json={
        'suite': 'repair', 'task_id': 'sample', 'mode': 'replay', 'workflow': 'repair-approval-v1'})
    assert response.status_code == 202, response.text
    return response.json()['id']


def test_real_worker_approval_survives_restart_and_exposes_evidence(tmp_path, monkeypatch):
    registry = tmp_path / 'bundles'
    bundle(registry / 'sample')
    monkeypatch.setenv('CORECODER_REPAIR_BUNDLES', str(registry))
    output = tmp_path / 'service'
    with TestClient(create_app(output, timeout=60)) as client:
        assert client.get('/catalog').json()['repair'][0]['task_id'] == 'sample'
        task_id = submit(client)
        assert submit(client) == task_id
        wait(client, task_id, lambda row: row['state'] == 'awaiting_approval')
        assert not (output / task_id / 'runs').exists()
    with TestClient(create_app(output, timeout=60)) as client:
        assert client.get(f'/tasks/{task_id}').json()['state'] == 'awaiting_approval'
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).status_code == 202
        result = wait(client, task_id, timeout=45)
        assert result['state'] == 'succeeded', result
        assert result['result']['fresh_model_calls'] == 0 and result['result']['execution_mode'] == 'replay'
        for name in ('report.json', 'patch.diff', 'context-selection.json', 'trace.jsonl', 'provenance.json'):
            assert client.get(f'/tasks/{task_id}/artifacts/{name}').status_code == 200
        assert 'awaiting_approval' in client.get(f'/tasks/{task_id}/events').text
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).json()['state'] == 'succeeded'
        assert client.get(f'/tasks/{task_id}/artifacts/job.json').status_code == 404


@pytest.mark.parametrize('action', ['reject', 'cancel'])
def test_rejected_or_cancelled_task_performs_no_inference(tmp_path, monkeypatch, action):
    bundle(tmp_path / 'bundles/sample')
    monkeypatch.setenv('CORECODER_REPAIR_BUNDLES', str(tmp_path / 'bundles'))
    with TestClient(create_app(tmp_path / 'service')) as client:
        task_id = submit(client)
        wait(client, task_id, lambda row: row['state'] == 'awaiting_approval')
        if action == 'reject':
            client.post(f'/tasks/{task_id}/approval', json={'decision': 'reject'})
            assert wait(client, task_id)['state'] == 'rejected'
        else:
            assert client.post(f'/tasks/{task_id}/cancel').json()['state'] == 'cancelled'
        assert not (tmp_path / 'service' / task_id / 'runs').exists()
