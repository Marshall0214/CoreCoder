import hashlib
import json
import time

import pytest

pytest.importorskip('fastapi')
pytest.importorskip('httpx')
pytest.importorskip('psutil')
from fastapi.testclient import TestClient

from service import tentative
from service.app import create_app
from service.worker import execute as execute_service_job
from tests.tentative_service_worker_stub import fixture
from tests.test_service import wait


def app(tmp_path, monkeypatch, **kwargs):
    fixture_root = tmp_path/'registered'
    fixture_root.mkdir()
    source, task = fixture(fixture_root)
    monkeypatch.setattr(tentative, 'load_task', lambda task_id: (source, task))
    return create_app(tmp_path/'service', worker_module='tests.tentative_service_worker_stub', **kwargs)


def submit(client, task_id=tentative.TASKS[0]):
    response = client.post('/tasks', json={'suite': 'certified', 'task_id': task_id,
                                          'mode': 'live', 'workflow': tentative.WORKFLOW})
    assert response.status_code == 202, response.text
    row = response.json()
    return row['id']


def test_approve_runs_actual_public_gate_and_publishes(tmp_path, monkeypatch):
    application = app(tmp_path, monkeypatch)
    with TestClient(application) as client:
        task_id = submit(client)
        wait(client, task_id, lambda r: r['state'] == 'awaiting_approval')
        root = tmp_path/'service'/task_id
        source = root/'source/src/pkg/__init__.py'
        assert source.read_text() == 'def f():\n    return 1\n'
        assert not (root/'inference-started').exists()
        snapshot = client.get(f'/tasks/{task_id}/artifacts/workflow.json').json()
        assert snapshot['plan']['max_llm_calls'] == 2
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).status_code == 202
        row = wait(client, task_id)
        assert row['state'] == 'succeeded' and row['result']['publication']['committed']
        assert source.read_text() == 'def f():\n    return 3\n'
        assert client.get(f'/tasks/{task_id}/artifacts/transaction.json').json()['accepted']
        assert client.get(f'/tasks/{task_id}/artifacts/lifecycle.json').json()['committed']
        assert '+    return 3' in client.get(f'/tasks/{task_id}/artifacts/patch.diff').text
        assert client.get(f'/tasks/{task_id}/artifacts/report.json').json()['verification']['scope'].startswith('certified public')
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).json()['state'] == 'succeeded'
        assert (root/'inference-started').read_text() == '1'
        assert client.post(f'/tasks/{task_id}/approval', json={'decision': 'reject'}).status_code == 409
        assert 'awaiting_approval' in client.get(f'/tasks/{task_id}/events').text


def test_failed_candidate_preserves_source_and_diagnostics(tmp_path, monkeypatch):
    with TestClient(app(tmp_path, monkeypatch)) as client:
        task_id = submit(client, tentative.TASKS[1])
        wait(client, task_id, lambda r: r['state'] == 'awaiting_approval')
        client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'})
        row = wait(client, task_id)
        assert row['state'] == 'failed' and not row['result']['accepted']
        assert row['result']['original_unchanged'] and not row['result']['publication']['committed']
        root = tmp_path/'service'/task_id
        assert (root/'source/src/pkg/__init__.py').read_text() == 'def f():\n    return 1\n'
        assert (root/'inference-started').read_text() == '2'
        assert client.get(f'/tasks/{task_id}/artifacts/patch.diff').text == ''
        assert client.get(f'/tasks/{task_id}/artifacts/transaction.json').json()['reason'] == 'public_check_failed'


@pytest.mark.parametrize('action', ['reject', 'cancel'])
def test_reject_or_cancel_approval_performs_no_inference(tmp_path, monkeypatch, action):
    with TestClient(app(tmp_path, monkeypatch)) as client:
        task_id = submit(client)
        wait(client, task_id, lambda r: r['state'] == 'awaiting_approval')
        if action == 'reject':
            client.post(f'/tasks/{task_id}/approval', json={'decision': 'reject'})
            assert wait(client, task_id)['state'] == 'rejected'
        else:
            assert client.post(f'/tasks/{task_id}/cancel').json()['state'] == 'cancelled'
        root = tmp_path/'service'/task_id
        assert not (root/'inference-started').exists()
        assert (root/'source/src/pkg/__init__.py').read_text() == 'def f():\n    return 1\n'


def test_cancel_during_inference_preserves_source(tmp_path, monkeypatch):
    monkeypatch.setenv('CORECODER_TENTATIVE_TEST_DELAY', '30')
    with TestClient(app(tmp_path, monkeypatch)) as client:
        task_id = submit(client)
        wait(client, task_id, lambda r: r['state'] == 'awaiting_approval')
        client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'})
        root = tmp_path/'service'/task_id
        end = time.monotonic()+15
        while not (root/'inference-started').exists() and time.monotonic() < end:
            time.sleep(.03)
        assert (root/'inference-started').exists()
        client.post(f'/tasks/{task_id}/cancel')
        assert wait(client, task_id)['state'] == 'cancelled'
        assert (root/'source/src/pkg/__init__.py').read_text() == 'def f():\n    return 1\n'
        assert not (root/'runs/tentative/publication/transaction.json').exists()


@pytest.mark.parametrize('changes', [{'suite': 'smoke'}, {'mode': 'scripted'}, {'search_backend': 'keyword'}, {'workflow': None}])
def test_mismatched_certified_configuration_rejected_before_queue(tmp_path, monkeypatch, changes):
    with TestClient(app(tmp_path, monkeypatch)) as client:
        body = {'suite': 'certified', 'task_id': tentative.TASKS[0], 'mode': 'live', 'workflow': tentative.WORKFLOW}
        body.update(changes)
        assert client.post('/tasks', json=body).status_code == 422
        assert not client.app.state.manager.jobs


def test_approval_survives_service_restart_without_inference(tmp_path, monkeypatch):
    application = app(tmp_path, monkeypatch)
    with TestClient(application) as client:
        task_id = submit(client)
        wait(client, task_id, lambda r: r['state'] == 'awaiting_approval')
    root = tmp_path/'service'/task_id
    assert not (root/'inference-started').exists()
    with TestClient(application) as client:
        assert client.get(f'/tasks/{task_id}').json()['state'] == 'awaiting_approval'
        client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'})
        assert wait(client, task_id)['state'] == 'succeeded'
        assert (root/'inference-started').read_text() == '1'


def test_changed_source_while_awaiting_approval_stops_before_inference(tmp_path, monkeypatch):
    with TestClient(app(tmp_path, monkeypatch)) as client:
        task_id = submit(client)
        wait(client, task_id, lambda r: r['state'] == 'awaiting_approval')
        root = tmp_path/'service'/task_id
        source = root/'source/src/pkg/__init__.py'
        source.write_text('def f():\n    return 9\n', encoding='utf-8')
        client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'})
        assert wait(client, task_id)['state'] == 'failed'
        assert not (root/'inference-started').exists()
        assert source.read_text() == 'def f():\n    return 9\n'


def test_missing_certificate_or_unknown_task_not_queued(tmp_path, monkeypatch):
    with TestClient(app(tmp_path, monkeypatch)) as client:
        def missing(task_id):
            raise ValueError('Changed input')
        monkeypatch.setattr(tentative, 'load_task', missing)
        body = {'suite': 'certified', 'task_id': tentative.TASKS[0], 'mode': 'live', 'workflow': tentative.WORKFLOW}
        assert client.post('/tasks', json=body).status_code == 503
        body['task_id'] = 'unknown'
        assert client.post('/tasks', json=body).status_code == 422
        assert not client.app.state.manager.jobs


def test_timeout_during_inference_preserves_source(tmp_path, monkeypatch):
    monkeypatch.setenv('CORECODER_TENTATIVE_TEST_DELAY', '30')
    with TestClient(app(tmp_path, monkeypatch, timeout=4)) as client:
        task_id = submit(client)
        wait(client, task_id, lambda r: r['state'] == 'awaiting_approval')
        client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'})
        assert wait(client, task_id)['state'] == 'timed_out'
        root = tmp_path/'service'/task_id
        assert (root/'inference-started').exists()
        assert (root/'source/src/pkg/__init__.py').read_text() == 'def f():\n    return 1\n'


def test_changed_certified_experiment_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(tentative, 'RECORD', tmp_path)
    (tmp_path/'experiment.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='Certified experiment changed'):
        tentative.load_task(tentative.TASKS[0])


def test_changed_job_template_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(tentative, 'RECORD', tmp_path)
    record = tmp_path/'experiment.json'
    record.write_text(json.dumps({'complete': True, 'protocol': {'adapter_hashes': {}}}), encoding='utf-8')
    monkeypatch.setattr(tentative, 'RECORD_SHA256', hashlib.sha256(record.read_bytes()).hexdigest())
    job = tmp_path/tentative.TASKS[0]/'tentative-publication/job.json'
    job.parent.mkdir(parents=True)
    job.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='Certified job template changed'):
        tentative.load_task(tentative.TASKS[0])


def test_service_setup_failure_is_sanitized_and_checkpoint_failed(tmp_path, monkeypatch):
    job = tmp_path/'job.json'
    job.write_text(json.dumps({'request': {'workflow': tentative.WORKFLOW}}), encoding='utf-8')
    checkpoint = tmp_path/'workflow.json'
    checkpoint.write_text(json.dumps({'stage': 'executing'}), encoding='utf-8')
    def failure(*args, **kwargs):
        raise ValueError('provider secret should never be exposed')
    monkeypatch.setattr(tentative, 'run', failure)
    execute_service_job(job)
    result = json.loads((tmp_path/'result.json').read_text(encoding='utf-8'))
    assert result['status'] == 'service_execution_error' and result['failure_type'] == 'ValueError'
    assert result['verification']['passed'] is False
    assert 'secret' not in json.dumps(result)
    assert json.loads(checkpoint.read_text(encoding='utf-8'))['stage'] == 'failed'
