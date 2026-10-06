import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip('fastapi')
pytest.importorskip('httpx')
psutil = pytest.importorskip('psutil')

from fastapi.testclient import TestClient

from service.app import SubmitTask, create_app
from service.launcher import await_approval
from service.manager import ROOT, Job, stop_tree
from service.store import TaskStore
from tests.test_service import submit, wait

BODY = {'task_id': 'timeout-units'}
STUB = 'tests.service_worker_stub'


def seed(root, state='queued', mode='scripted', key=None, process=None, birth=None):
    root.mkdir(exist_ok=True)
    job = Job(uuid.uuid4().hex, SubmitTask(task_id='timeout-units', mode=mode).model_dump(), root / uuid.uuid4().hex)
    job.root = root / job.id
    job.root.mkdir()
    (job.root / 'job.json').write_text(json.dumps({'request': job.request}), encoding='utf-8')
    store = TaskStore(root)
    try:
        job.transition('queued')
        store.insert(job, key)
        job.store = store
        if state != 'queued':
            job.pid = process.pid if process else None
            job.process_started_at = birth
            job.transition(state)
    finally:
        store.close()
    return job


def test_finished_task_and_events_survive_restart(tmp_path):
    headers = {'Idempotency-Key': 'repair-001'}
    with TestClient(create_app(tmp_path)) as client:
        task_id = client.post('/tasks', json=BODY, headers=headers).json()['id']
        original = wait(client, task_id)
        assert original['state'] == 'succeeded'
        patch = client.get(f'/tasks/{task_id}/artifacts/patch.diff').text
    app = create_app(tmp_path)
    with TestClient(app) as client:
        assert client.get(f'/tasks/{task_id}').json() == original
        assert client.post('/tasks', json=BODY, headers=headers).json()['id'] == task_id
        assert app.state.manager.jobs[task_id].handle is None
        assert app.state.manager.jobs[task_id].process is None
        assert client.get(f'/tasks/{task_id}/artifacts/patch.diff').text == patch
        replay = client.get(f'/tasks/{task_id}/events', headers={'Last-Event-ID': '2'}).text
        assert 'id: 3' in replay and 'id: 1' not in replay
        assert len(list(tmp_path.glob('*/runs/*/workspace'))) == 1


def test_concurrent_idempotency_conflict_and_invalid_key(tmp_path):
    headers = {'Idempotency-Key': 'one-task'}
    with TestClient(create_app(tmp_path, worker_module=STUB)) as client:
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: client.post('/tasks', json=BODY, headers=headers), range(8)))
        assert all(r.status_code == 202 for r in responses)
        ids = {r.json()['id'] for r in responses}
        assert len(ids) == 1
        assert wait(client, ids.pop())['state'] == 'succeeded'
        assert client.post('/tasks', json={**BODY, 'mode': 'reference'}, headers=headers).status_code == 409
        assert client.post('/tasks', json=BODY, headers={'Idempotency-Key': 'bad key'}).status_code == 400
        assert len([p for p in tmp_path.iterdir() if p.is_dir()]) == 1


def test_idempotent_replay_works_when_queue_is_full(tmp_path):
    body = {**BODY, 'mode': 'unchanged'}
    headers = {'Idempotency-Key': 'busy'}
    with TestClient(create_app(tmp_path, capacity=1, worker_module=STUB)) as client:
        task_id = client.post('/tasks', json=body, headers=headers).json()['id']
        wait(client, task_id, lambda row: row['state'] == 'running')
        assert client.post('/tasks', json=body, headers=headers).json()['id'] == task_id
        assert client.post('/tasks', json=BODY).status_code == 429


def test_queued_task_is_recovered_once(tmp_path):
    queued = seed(tmp_path, key='queued')
    with TestClient(create_app(tmp_path)) as client:
        assert wait(client, queued.id)['state'] == 'succeeded'
        events = client.get(f'/tasks/{queued.id}/events').text
        assert events.count('event: state') == 3
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(f'/tasks/{queued.id}').json()['state'] == 'succeeded'
        assert client.get(f'/tasks/{queued.id}/events').text == events
        assert len(list(tmp_path.glob('*/runs/*/workspace'))) == 1


@pytest.mark.parametrize('state', ['running', 'cancelling'])
def test_inflight_tasks_are_interrupted_without_retry(tmp_path, state):
    job = seed(tmp_path, state=state, key='inflight')
    with TestClient(create_app(tmp_path, worker_module=STUB)) as client:
        assert client.get(f'/tasks/{job.id}').json()['state'] == 'interrupted'
        response = client.post('/tasks', json=BODY, headers={'Idempotency-Key': 'inflight'})
        assert response.status_code == 202 and response.json()['id'] == job.id
        assert not (job.root / 'result.json').exists()
        assert 'interrupted' in client.get(f'/tasks/{job.id}/events').text
    with TestClient(create_app(tmp_path, worker_module=STUB)) as client:
        assert client.get(f'/tasks/{job.id}/events').text.count('event: state') == 3


def test_history_is_bounded_and_expired_key_cannot_rerun(tmp_path):
    with TestClient(create_app(tmp_path, retention=1, worker_module=STUB)) as client:
        old = client.post('/tasks', json=BODY, headers={'Idempotency-Key': 'old'}).json()['id']
        wait(client, old)
        new = submit(client)
        wait(client, new)
        assert client.get(f'/tasks/{old}').status_code == 404
        assert client.post('/tasks', json=BODY, headers={'Idempotency-Key': 'old'}).status_code == 410
        assert client.post('/tasks', json={**BODY, 'mode': 'live'}, headers={'Idempotency-Key': 'old'}).status_code == 409
        assert (tmp_path / old).is_dir()
        assert len(client.app.state.manager.jobs) == 1
    with sqlite3.connect(tmp_path / 'tasks.sqlite3') as db:
        assert db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 3
        assert db.execute('SELECT COUNT(*) FROM idempotency').fetchone()[0] == 1


def test_data_directory_has_one_owner(tmp_path):
    with (TestClient(create_app(tmp_path)), pytest.raises(RuntimeError, match='already has an owner'),
          TestClient(create_app(tmp_path))):
        pass
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/health').status_code == 200


@pytest.mark.parametrize('matching', [True, False])
def test_orphan_cleanup_checks_process_identity(tmp_path, matching):
    job = seed(tmp_path, mode='unchanged')
    process = subprocess.Popen([sys.executable, '-m', STUB, str(job.root / 'job.json')],
                               env=dict(os.environ, PYTHONPATH=str(ROOT)), stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, cwd=ROOT)
    try:
        deadline = time.monotonic() + 10
        while not (job.root / 'pids.json').exists() and time.monotonic() < deadline:
            time.sleep(0.03)
        assert (job.root / 'pids.json').exists()
        pids = json.loads((job.root / 'pids.json').read_text())
        store = TaskStore(tmp_path)
        job.store = store
        job.pid = process.pid
        job.process_started_at = psutil.Process(process.pid).create_time() + (0 if matching else 1)
        try:
            job.transition('running')
        finally:
            store.close()
        with TestClient(create_app(tmp_path, worker_module=STUB)) as client:
            assert client.get(f'/tasks/{job.id}').json()['state'] == 'interrupted'
            if matching:
                assert process.poll() is not None
                assert all(not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE for pid in pids)
            else:
                assert process.poll() is None
    finally:
        if process.poll() is None:
            stop_tree(process)


def test_launch_requires_approval(tmp_path):
    path = tmp_path / 'job.json'
    assert not await_approval(path, timeout=0.05)
    identity = json.loads((tmp_path / 'worker-identity.json').read_text())
    assert identity['pid'] == os.getpid()
    assert identity['process_started_at'] == psutil.Process().create_time()
    (tmp_path / 'start-approved').touch()
    assert await_approval(path, timeout=0.05)


def test_unapproved_orphan_is_stopped_without_executing(tmp_path):
    job = seed(tmp_path, state='running')
    process = subprocess.Popen([sys.executable, '-m', 'service.launcher', STUB, str(job.root / 'job.json')],
                               env=dict(os.environ, PYTHONPATH=str(ROOT)), stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, cwd=ROOT)
    try:
        deadline = time.monotonic() + 10
        while not (job.root / 'worker-identity.json').exists() and time.monotonic() < deadline:
            time.sleep(0.03)
        assert (job.root / 'worker-identity.json').exists()
        with TestClient(create_app(tmp_path, worker_module=STUB)) as client:
            assert client.get(f'/tasks/{job.id}').json()['state'] == 'interrupted'
            assert process.poll() is not None
            assert not (job.root / 'result.json').exists()
            assert not (job.root / 'start-approved').exists()
    finally:
        if process.poll() is None:
            stop_tree(process)
