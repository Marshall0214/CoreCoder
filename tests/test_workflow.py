import json
import time
from pathlib import Path

import pytest

pytest.importorskip('langgraph')
pytest.importorskip('fastapi')
pytest.importorskip('httpx')
psutil = pytest.importorskip('psutil')

from fastapi.testclient import TestClient

from evals.schema import RunConfig, load_suite
from service.app import create_app
from tests.test_service import process_stopped, wait
from workflows.repair import RepairPlan, run_workflow

SUITE = Path(__file__).resolve().parent.parent / 'evals/fixtures'


@pytest.mark.parametrize('mode,accepted', [('scripted', True), ('unchanged', False)])
def test_graph_uses_real_independent_verification(tmp_path, mode, accepted):
    task = load_suite(SUITE, ['timeout-units'])[0]
    report = run_workflow(task, RunConfig(mode=mode), tmp_path)
    snapshot = json.loads((tmp_path / 'workflow.json').read_text(encoding='utf-8'))
    assert report['accepted'] is accepted and report['verification']['passed'] is accepted
    assert snapshot['outcome'] == ('accepted' if accepted else 'rejected')
    assert snapshot['plan']['attempt_limit'] == 1
    assert [e['stage'] for e in snapshot['events']] == ['planned', 'executing', 'reviewing', snapshot['stage']]
    assert len(list((tmp_path / 'runs').iterdir())) == 1


def test_false_success_is_rejected_without_a_retry(tmp_path):
    calls = []

    def execute(task, config, output):
        calls.append(task.task_id)
        return {'status': 'passed', 'accepted': True, 'verification': {'passed': False}}

    report = run_workflow(load_suite(SUITE, ['timeout-units'])[0], RunConfig(), tmp_path, execute)
    assert calls == ['timeout-units'] and report['accepted'] is False
    assert report['status'] == 'failed_verification'
    assert json.loads((tmp_path / 'workflow.json').read_text())['outcome'] == 'rejected'


def test_adapter_error_is_recorded_without_credentials_or_retry(tmp_path):
    calls = []

    def execute(*args):
        calls.append(1)
        raise RuntimeError('secret-key-must-not-be-recorded')

    with pytest.raises(RuntimeError):
        run_workflow(load_suite(SUITE, ['timeout-units'])[0], RunConfig(), tmp_path, execute)
    text = (tmp_path / 'workflow.json').read_text()
    assert calls == [1] and 'secret-key' not in text
    assert json.loads(text)['error_type'] == 'RuntimeError'


def test_plan_rejects_unbounded_attempts():
    with pytest.raises(ValueError):
        RepairPlan(task_id='test', allowed_files=['a.py'], mode='scripted', token_budget=100, attempt_limit=2)


def test_existing_snapshot_cannot_repeat_side_effects(tmp_path):
    task = load_suite(SUITE, ['timeout-units'])[0]
    calls = []

    def execute(*args):
        calls.append(1)
        return {'status': 'passed', 'accepted': True, 'verification': {'passed': True}}

    run_workflow(task, RunConfig(), tmp_path, execute)
    with pytest.raises(ValueError, match='snapshot'):
        run_workflow(task, RunConfig(), tmp_path, execute)
    assert calls == [1]


def test_graph_output_cannot_write_into_fixtures():
    task = load_suite(SUITE, ['timeout-units'])[0]
    with pytest.raises(ValueError, match='fixtures'):
        run_workflow(task, RunConfig(), task.root / 'never-create-workflow')
    assert not (task.root / 'never-create-workflow').exists()


def test_api_workflow_artifact_and_persisted_idempotency(tmp_path):
    body = {'task_id': 'timeout-units', 'workflow': 'langgraph-v1'}
    headers = {'Idempotency-Key': 'graph'}
    with TestClient(create_app(tmp_path)) as client:
        response = client.post('/tasks', json=body, headers=headers)
        assert response.status_code == 202
        task_id = response.json()['id']
        assert wait(client, task_id)['state'] == 'succeeded'
        snapshot = client.get(f'/tasks/{task_id}/artifacts/workflow.json').json()
        assert snapshot['outcome'] == 'accepted'
        assert client.post('/tasks', json={'task_id': 'timeout-units'}, headers=headers).status_code == 409
    with TestClient(create_app(tmp_path)) as client:
        assert client.post('/tasks', json=body, headers=headers).json()['id'] == task_id
        assert client.get(f'/tasks/{task_id}/artifacts/workflow.json').json() == snapshot
        assert len(list((tmp_path / task_id / 'runs').iterdir())) == 1


def test_legacy_request_with_explicit_null_keeps_original_key(tmp_path):
    body = {'task_id': 'timeout-units'}
    headers = {'Idempotency-Key': 'legacy'}
    with TestClient(create_app(tmp_path)) as client:
        task_id = client.post('/tasks', json=body, headers=headers).json()['id']
        assert wait(client, task_id)['state'] == 'succeeded'
        assert client.post('/tasks', json={**body, 'workflow': None}, headers=headers).json()['id'] == task_id
        saved = json.loads((tmp_path / task_id / 'job.json').read_text())['request']
        assert 'workflow' not in saved
        assert client.get(f'/tasks/{task_id}/artifacts/workflow.json').status_code == 404


def test_missing_optional_dependency_rejects_only_graph_requests(tmp_path, monkeypatch):
    monkeypatch.setattr('service.app.find_spec', lambda name: None)
    with TestClient(create_app(tmp_path)) as client:
        assert client.post('/tasks', json={'task_id': 'timeout-units', 'workflow': 'langgraph-v1'}).status_code == 503
        assert client.post('/tasks', json={'task_id': 'timeout-units', 'workflow': 'unknown'}).status_code == 422
        assert not client.app.state.manager.jobs


def test_running_graph_cancel_stops_children_and_preserves_last_stage(tmp_path):
    with TestClient(create_app(tmp_path, worker_module='tests.workflow_worker_stub')) as client:
        response = client.post('/tasks', json={'task_id': 'timeout-units', 'mode': 'unchanged', 'workflow': 'langgraph-v1'})
        task_id = response.json()['id']
        deadline = time.monotonic() + 15
        pid_file = tmp_path / task_id / 'pids.json'
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.03)
        assert pid_file.exists()
        pids = json.loads(pid_file.read_text())
        assert client.get(f'/tasks/{task_id}/artifacts/workflow.json').json()['stage'] == 'executing'
        client.post(f'/tasks/{task_id}/cancel')
        assert wait(client, task_id)['state'] == 'cancelled'
        assert all(process_stopped(pid) for pid in pids)
        partial = client.get(f'/tasks/{task_id}/artifacts/workflow.json').json()
        assert partial['stage'] == 'executing' and partial['outcome'] == 'pending'
        assert not (tmp_path / task_id / 'result.json').exists()
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f'/tasks/{task_id}').json()['state'] == 'cancelled'
        assert client.get(f'/tasks/{task_id}/artifacts/workflow.json').json() == partial
