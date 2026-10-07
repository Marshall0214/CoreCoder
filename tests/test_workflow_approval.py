import json
import sqlite3
import time
from pathlib import Path

import pytest

pytest.importorskip('langgraph.checkpoint.sqlite')
pytest.importorskip('fastapi')
pytest.importorskip('httpx')
psutil = pytest.importorskip('psutil')

from fastapi.testclient import TestClient

from evals.schema import RunConfig, load_suite
from service.app import create_app
from service.manager import Job
from service.store import TaskStore
from tests.test_service import wait
from workflows.approval import run_approval_workflow

SUITE = Path(__file__).resolve().parent.parent / 'evals/fixtures'
BODY = {'task_id': 'timeout-units', 'workflow': 'langgraph-approval-v1'}


def awaiting(client, task_id):
    return wait(client, task_id, predicate=lambda row: row['state'] == 'awaiting_approval')


def test_native_checkpoint_resume_does_not_replan_or_execute_before_approval(tmp_path):
    task = load_suite(SUITE, ['timeout-units'])[0]
    calls = []

    def execute(*args):
        calls.append(1)
        return {'status': 'passed', 'accepted': True, 'verification': {'passed': True}}

    assert run_approval_workflow(task, RunConfig(), tmp_path, execute=execute)['status'] == 'awaiting_approval'
    assert calls == [] and not (tmp_path / 'execution-started').exists()
    with sqlite3.connect(tmp_path / 'checkpoints.sqlite3') as db:
        assert db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0] > 0
    assert run_approval_workflow(task, RunConfig(), tmp_path, execute=execute)['status'] == 'awaiting_approval'
    result = run_approval_workflow(task, RunConfig(), tmp_path, decision='approve', execute=execute)
    assert result['accepted'] and calls == [1]
    assert run_approval_workflow(task, RunConfig(), tmp_path, decision='approve', execute=execute) == result
    assert calls == [1]
    snapshot = json.loads((tmp_path / 'workflow.json').read_text())
    assert [e['stage'] for e in snapshot['events']].count('planned') == 1
    assert snapshot['decision'] == 'approve' and snapshot['outcome'] == 'accepted'
    with pytest.raises(ValueError, match='another approval'):
        run_approval_workflow(task, RunConfig(), tmp_path, decision='reject', execute=execute)


def test_reject_and_changed_config_cannot_execute(tmp_path):
    task = load_suite(SUITE, ['timeout-units'])[0]

    def never_execute(*args):
        pytest.fail('Rejected plan executed')

    run_approval_workflow(task, RunConfig(), tmp_path, execute=never_execute)
    with pytest.raises(ValueError, match='another request'):
        run_approval_workflow(task, RunConfig(token_budget=20000), tmp_path, decision='approve', execute=never_execute)
    result = run_approval_workflow(task, RunConfig(), tmp_path, decision='reject', execute=never_execute)
    assert result['status'] == 'approval_rejected' and not (tmp_path / 'runs').exists()


def test_failed_side_effect_is_never_replayed(tmp_path):
    task = load_suite(SUITE, ['timeout-units'])[0]
    calls = []

    def execute(*args):
        calls.append(1)
        raise RuntimeError('secret-credential')

    run_approval_workflow(task, RunConfig(), tmp_path, execute=execute)
    with pytest.raises(RuntimeError):
        run_approval_workflow(task, RunConfig(), tmp_path, decision='approve', execute=execute)
    with pytest.raises(ValueError, match='already started'):
        run_approval_workflow(task, RunConfig(), tmp_path, decision='approve', execute=execute)
    assert calls == [1] and 'secret-credential' not in (tmp_path / 'workflow.json').read_text()


def test_approval_requires_persisted_interrupt_and_safe_output(tmp_path):
    task = load_suite(SUITE, ['timeout-units'])[0]
    with pytest.raises(ValueError, match='awaiting approval'):
        run_approval_workflow(task, RunConfig(), tmp_path, decision='approve')
    with pytest.raises(ValueError, match='fixtures'):
        run_approval_workflow(task, RunConfig(), task.root / 'never-create-approval')
    assert not (task.root / 'never-create-approval').exists()


@pytest.mark.parametrize('mode,expected', [('scripted', 'succeeded'), ('unchanged', 'failed')])
def test_api_pending_survives_shutdown_and_resumes_real_verification(tmp_path, mode, expected):
    body = {**BODY, 'mode': mode}
    with TestClient(create_app(tmp_path, concurrency=1)) as client:
        task_id = client.post('/tasks', json=body, headers={'Idempotency-Key': 'approval'}).json()['id']
        row = awaiting(client, task_id)
        assert row['approval'] is None and row['result'] is None
        assert not (tmp_path / task_id / 'runs').exists()
        assert client.get(f'/tasks/{task_id}/artifacts/checkpoints.sqlite3').status_code == 404
        # The waiting task consumes capacity but releases its worker/concurrency slot.
        other = client.post('/tasks', json={'task_id': 'timeout-units'}).json()['id']
        assert wait(client, other)['state'] == 'succeeded'
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f'/tasks/{task_id}').json() == row
        assert client.post('/tasks', json=body, headers={'Idempotency-Key': 'approval'}).json()['id'] == task_id
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).status_code == 202
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).status_code == 202
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'reject'}).status_code == 409
        completed = wait(client, task_id)
        assert completed['state'] == expected and completed['approval'] == 'approve'
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).json() == completed
        assert len(list((tmp_path / task_id / 'runs').iterdir())) == 1
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).json() == completed
        assert len(list((tmp_path / task_id / 'runs').iterdir())) == 1


@pytest.mark.parametrize('action,expected', [('reject', 'rejected'), ('cancel', 'cancelled')])
def test_waiting_rejection_or_cancellation_never_executes(tmp_path, action, expected):
    with TestClient(create_app(tmp_path, capacity=1)) as client:
        task_id = client.post('/tasks', json=BODY).json()['id']
        awaiting(client, task_id)
        assert client.post('/tasks', json=BODY).status_code == 429
        if action == 'cancel':
            client.post(f'/tasks/{task_id}/cancel')
            assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).status_code == 409
        else:
            client.post(f'/tasks/{task_id}/approval', json={'decision': 'reject'})
        assert wait(client, task_id)['state'] == expected
        assert not (tmp_path / task_id / 'runs').exists()
        assert not (tmp_path / task_id / 'execution-started').exists()
        assert expected in client.get(f'/tasks/{task_id}/events').text
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f'/tasks/{task_id}').json()['state'] == expected


def test_approval_endpoint_validation_and_dependency_failure(tmp_path, monkeypatch):
    with TestClient(create_app(tmp_path)) as client:
        assert client.post('/tasks/unknown/approval', json={'decision': 'approve'}).status_code == 404
        task_id = client.post('/tasks', json={'task_id': 'timeout-units'}).json()['id']
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).status_code == 409
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'yes'}).status_code == 422
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve', 'extra': 1}).status_code == 422
        monkeypatch.setattr('service.app.find_spec', lambda name: None if name.endswith('.sqlite') else True)
        assert client.post('/tasks', json=BODY).status_code == 503


def test_persisted_approval_recovers_queue_before_worker_launch(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        task_id = client.post('/tasks', json=BODY).json()['id']
        awaiting(client, task_id)
    store = TaskStore(tmp_path)
    try:
        job = Job(**store.load()[0], root=tmp_path / task_id, store=store)
        job.approval = 'approve'
        job.transition('queued')  # Simulate process loss after durable decision, before scheduling.
    finally:
        store.close()
    with TestClient(create_app(tmp_path)) as client:
        assert wait(client, task_id)['state'] == 'succeeded'
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).status_code == 202
        assert len(list((tmp_path / task_id / 'runs').iterdir())) == 1


def test_approved_running_cancel_stops_actual_children(tmp_path):
    with TestClient(create_app(tmp_path, worker_module='tests.approval_worker_stub')) as client:
        task_id = client.post('/tasks', json={**BODY, 'mode': 'unchanged'}).json()['id']
        awaiting(client, task_id)
        client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'})
        path = tmp_path / task_id / 'pids.json'
        deadline = time.monotonic() + 15
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.03)
        assert path.exists()
        pids = json.loads(path.read_text())
        client.post(f'/tasks/{task_id}/cancel')
        assert wait(client, task_id)['state'] == 'cancelled'
        assert all(not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE for pid in pids)
        assert (tmp_path / task_id / 'execution-started').exists()
        assert not (tmp_path / task_id / 'result.json').exists()
