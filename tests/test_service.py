import json
import time

import pytest

pytest.importorskip('fastapi')
pytest.importorskip('httpx')
psutil = pytest.importorskip('psutil')

from fastapi.testclient import TestClient

from service.app import create_app
from service.manager import TERMINAL


def process_stopped(pid):
    # A child may disappear between PID lookup and status retrieval.
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


@pytest.mark.parametrize('status,stopped', [(psutil.STATUS_ZOMBIE, True), (psutil.STATUS_RUNNING, False)])
def test_process_stopped_preserves_live_process_assertion(monkeypatch, status, stopped):
    class Child:
        def status(self):
            return status
    monkeypatch.setattr(psutil, 'Process', lambda pid: Child())
    assert process_stopped(123) is stopped


def test_process_stopped_accepts_child_exiting_during_status_lookup(monkeypatch):
    class Child:
        def status(self):
            raise psutil.NoSuchProcess(123)
    monkeypatch.setattr(psutil, 'Process', lambda pid: Child())
    assert process_stopped(123)


def wait(client, task_id, predicate=lambda row: row['state'] in TERMINAL, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        row = client.get(f'/tasks/{task_id}').json()
        if predicate(row):
            return row
        time.sleep(0.03)
    raise AssertionError('Task did not reach expected state')


def submit(client, **kwargs):
    response = client.post('/tasks', json={'task_id': 'timeout-units', **kwargs})
    assert response.status_code == 202, response.text
    return response.json()['id']


def test_real_repair_verification_artifacts_and_replay(tmp_path):
    with TestClient(create_app(tmp_path, concurrency=2)) as client:
        assert client.get('/health').json() == {'status': 'ok'}
        assert len(client.get('/catalog').json()['smoke']) == 5
        good = submit(client)
        bad = submit(client, mode='unchanged')
        first, second = wait(client, good), wait(client, bad)
        assert first['state'] == 'succeeded' and first['result']['verification']['passed']
        assert second['state'] == 'failed' and not second['result']['accepted']
        assert (tmp_path / good).is_dir() and (tmp_path / bad).is_dir()
        workspaces = list(tmp_path.glob('*/runs/*/workspace'))
        assert len(workspaces) == 2 and workspaces[0] != workspaces[1]
        patch = client.get(f'/tasks/{good}/artifacts/patch.diff')
        assert patch.status_code == 200 and '---' in patch.text
        report = client.get(f'/tasks/{good}/artifacts/report.json').json()
        assert report['accepted'] and report['source'] == 'synthetic'
        assert client.get(f'/tasks/{good}/artifacts/job.json').status_code == 404
        events = client.get(f'/tasks/{good}/events')
        assert events.headers['content-type'].startswith('text/event-stream')
        records = [json.loads(line[6:]) for line in events.text.splitlines() if line.startswith('data: ')]
        assert [r['state'] for r in records] == ['queued', 'running', 'succeeded']
        assert all(r['id'] == good for r in records)
        replay = client.get(f'/tasks/{good}/events', headers={'Last-Event-ID': '2'}).text
        assert 'id: 3' in replay and 'id: 1' not in replay
        assert client.get(f'/tasks/{good}/events', headers={'Last-Event-ID': 'bad'}).status_code == 400
        assert client.post(f'/tasks/{good}/cancel').json()['state'] == 'succeeded'


@pytest.mark.parametrize('body', [{'task_id': '../escape'}, {'task_id': 'unknown'},
                                 {'task_id': 'timeout-units', 'suite': '../../'},
                                 {'task_id': 'timeout-units', 'base_url': 'http://other'},
                                 {'task_id': 'timeout-units', 'mode': 'arbitrary'}])
def test_invalid_inputs_do_not_spawn(tmp_path, body):
    with TestClient(create_app(tmp_path)) as client:
        assert client.post('/tasks', json=body).status_code == 422
        assert not any(path.is_dir() for path in tmp_path.iterdir())
        assert not client.app.state.manager.jobs
        assert client.get('/tasks/unknown').status_code == 404


def test_running_and_queued_cancel_and_capacity(tmp_path):
    app = create_app(tmp_path, capacity=2, worker_module='tests.service_worker_stub')
    with TestClient(app) as client:
        running = submit(client, mode='unchanged')
        wait(client, running, lambda r: r['state'] == 'running')
        end = time.monotonic() + 10
        while not (tmp_path / running / 'pids.json').exists() and time.monotonic() < end:
            time.sleep(0.03)
        assert (tmp_path / running / 'pids.json').exists()
        queued = submit(client, mode='unchanged')
        assert client.get(f'/tasks/{queued}').json()['state'] == 'queued'
        assert client.post('/tasks', json={'task_id': 'timeout-units'}).status_code == 429
        assert client.post(f'/tasks/{queued}/cancel').json()['state'] == 'cancelled'
        client.post(f'/tasks/{running}/cancel')
        assert wait(client, running)['state'] == 'cancelled'
        assert not (tmp_path / queued / 'pids.json').exists()
        assert app.state.manager.jobs[running].process.poll() is not None
        for pid in json.loads((tmp_path / running / 'pids.json').read_text()):
            assert process_stopped(pid)
        assert client.post(f'/tasks/{running}/cancel').json()['state'] == 'cancelled'
        assert 'cancelled' in client.get(f'/tasks/{running}/events').text


def test_timeout_crash_and_false_success(tmp_path):
    with TestClient(create_app(tmp_path, timeout=0.5, worker_module='tests.service_worker_stub')) as client:
        assert wait(client, submit(client, mode='unchanged'))['state'] == 'timed_out'
        assert wait(client, submit(client, mode='live'))['state'] == 'failed'
        false = wait(client, submit(client, mode='reference'))
        assert false['state'] == 'failed' and not false['result']['accepted']


def test_shutdown_stops_running_work(tmp_path):
    app = create_app(tmp_path, worker_module='tests.service_worker_stub')
    with TestClient(app) as client:
        task_id = submit(client, mode='unchanged')
        wait(client, task_id, lambda r: r['state'] == 'running')
    job = app.state.manager.jobs[task_id]
    assert job.state == 'cancelled' and job.process.poll() is not None
