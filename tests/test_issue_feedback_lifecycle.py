"""Issue partial delivery after actual worker termination; no model or Docker."""
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest

pytest.importorskip('fastapi')
pytest.importorskip('httpx')
pytest.importorskip('langgraph.checkpoint.sqlite')

from fastapi.testclient import TestClient

from service.app import create_app
from service.manager import Job, TaskManager, issue_artifact_path, partial_issue_report
from service.store import TaskStore
from tests.test_service import process_stopped, wait

BODY = {'suite': 'issues', 'task_id': 'slow', 'mode': 'scripted', 'search_backend': 'off',
        'workflow': 'issue-approval-v1'}
WORKER = 'tests.test_issue_feedback_lifecycle'


def public_progress(folder):
    runs = folder / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    # Deliberately stale success flags exercise the lifecycle normalization boundary.
    report = {'status': 'public_checks_passed', 'accepted': True, 'public_checks_passed': True,
              'delivery_status': 'ready_for_review', 'requires_review': False,
              'independent_verification': {'available': True, 'passed': True},
              'metrics': {'llm_calls': 0, 'prompt_tokens': None, 'completion_tokens': None},
              'fresh_model_calls': 0, 'execution_mode': 'scripted', 'original_unchanged': True,
              'changed_files': ['src/pkg/calc.py']}
    (runs / 'report.json').write_text(json.dumps(report), encoding='utf-8')
    (runs / 'patch.diff').write_text('--- a/src/pkg/calc.py\n+++ b/src/pkg/calc.py\n', encoding='utf-8')
    (runs / 'context-selection.json').write_text('{"partial":true}', encoding='utf-8')
    return report


def seeded(root, state='running', *, progress=True):
    root.mkdir(parents=True, exist_ok=True)
    task_id = uuid.uuid4().hex
    job = Job(task_id, dict(BODY), root / task_id)
    job.root.mkdir()
    (job.root / 'job.json').write_text(json.dumps({'request': job.request}), encoding='utf-8')
    if progress:
        public_progress(job.root)
    store = TaskStore(root)
    try:
        job.transition('queued')
        store.insert(job, None)
        job.store = store
        job.transition(state)
    finally:
        store.close()
    return job


@pytest.fixture
def no_docker(monkeypatch):
    owners = []
    monkeypatch.setattr(TaskManager, '_clean_sandbox', staticmethod(lambda job: owners.append(str(job.root))))
    return owners


def submission(client, task_id='slow'):
    response = client.post('/tasks', json={**BODY, 'task_id': task_id})
    assert response.status_code == 202, response.text
    return response.json()['id']


def wait_file(path, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.02)
    pytest.fail('Fixture worker did not publish its startup receipt')


@pytest.fixture
def trusted_stub(monkeypatch, no_docker):
    from service import issues

    monkeypatch.setattr(issues, 'load_task', lambda task_id: (None, {'scripted_responses': True}, None))
    return no_docker


@pytest.mark.parametrize('ending', ['cancelled', 'timed_out', 'failed'])
def test_actual_issue_worker_partial_artifacts_survive_termination(tmp_path, trusted_stub, ending):
    timeout = 2 if ending == 'timed_out' else 20
    name = 'fail-after-progress' if ending == 'failed' else 'slow'
    app = create_app(tmp_path, timeout=timeout, worker_module=WORKER)
    with TestClient(app) as client:
        task_id = submission(client, name)
        task_root = tmp_path / task_id
        marker = task_root / 'fixture-started.json'
        wait_file(marker)
        before = (task_root / 'runs/report.json').read_bytes()
        receipt = json.loads(marker.read_text(encoding='utf-8'))
        assert float(receipt['service_timeout']) == timeout
        if ending == 'cancelled':
            client.post(f'/tasks/{task_id}/cancel').raise_for_status()
        state = wait(client, task_id, timeout=20)
        assert state['state'] == ending and state['result']['partial_result'] is True
        assert state['result']['accepted'] is state['result']['public_checks_passed'] is False
        assert state['result']['delivery_status'] == 'not_delivered'
        assert process_stopped(receipt['pid'])
        assert not (task_root / 'result.json').exists()
        report = client.get(f'/tasks/{task_id}/artifacts/report.json')
        assert report.status_code == 200
        value = report.json()
        assert value['status'] == value['lifecycle_state'] == ending
        assert value['engine_status'] == 'public_checks_passed'
        assert value['accepted'] is value['public_checks_passed'] is False
        assert value['independent_verification'] == {'available': False, 'passed': None}
        assert value['delivery_status'] == 'not_delivered'
        assert client.get(f'/tasks/{task_id}/artifacts/patch.diff').status_code == 200
        assert client.get(f'/tasks/{task_id}/artifacts/context-selection.json').json() == {'partial': True}
        assert client.get(f'/tasks/{task_id}/artifacts/responses.json').status_code == 404
        assert (task_root / 'runs/report.json').read_bytes() == before
    assert str(task_root) in trusted_stub
    with TestClient(create_app(tmp_path, worker_module=WORKER)) as client:
        restored = client.get(f'/tasks/{task_id}').json()
        assert restored['state'] == ending and restored['result'] == state['result']
        assert client.get(f'/tasks/{task_id}/artifacts/report.json').json()['status'] == ending


def test_restart_collects_partial_issue_report_without_result_json_or_reexecution(tmp_path, no_docker):
    job = seeded(tmp_path)
    before = (job.root / 'runs/report.json').read_bytes()
    with TestClient(create_app(tmp_path, worker_module=WORKER)) as client:
        row = client.get(f'/tasks/{job.id}').json()
        assert row['state'] == 'interrupted' and row['result']['partial_result'] is True
        assert row['result']['accepted'] is False
        assert not (job.root / 'fixture-started.json').exists()
        assert not (job.root / 'result.json').exists()
        report = client.get(f'/tasks/{job.id}/artifacts/report.json').json()
        assert report['status'] == 'interrupted' and report['engine_status'] == 'public_checks_passed'
        assert client.get(f'/tasks/{job.id}/artifacts/patch.diff').status_code == 200
    assert no_docker == [str(job.root)]
    assert (job.root / 'runs/report.json').read_bytes() == before


@pytest.mark.parametrize(('task_id', 'state', 'engine_status'), [
    ('returned-timeout', 'timed_out', 'task_timeout'),
    ('returned-cancelled', 'cancelled', 'cancelled'),
])
def test_issue_engine_terminal_status_is_preserved_after_clean_worker_exit(
        tmp_path, trusted_stub, task_id, state, engine_status):
    with TestClient(create_app(tmp_path, timeout=20, worker_module=WORKER)) as client:
        job_id = submission(client, task_id)
        result = wait(client, job_id, timeout=20)
        assert result['state'] == state
        assert (tmp_path / job_id / 'result.json').is_file()
        assert result['result']['accepted'] is result['result']['public_checks_passed'] is False
        report = client.get(f'/tasks/{job_id}/artifacts/report.json').json()
        assert report['status'] == state and report['engine_status'] == engine_status
        assert report['delivery_status'] == 'not_delivered'


def test_cancelled_before_execution_has_no_fabricated_artifacts(tmp_path, no_docker):
    job = seeded(tmp_path, 'cancelled', progress=False)
    with TestClient(create_app(tmp_path, worker_module=WORKER)) as client:
        assert client.get(f'/tasks/{job.id}').json()['result'] is None
        assert client.get(f'/tasks/{job.id}/artifacts/report.json').status_code == 404
        assert client.get(f'/tasks/{job.id}/artifacts/patch.diff').status_code == 404


def test_malformed_partial_report_does_not_prevent_interrupted_recovery(tmp_path, no_docker):
    job = seeded(tmp_path)
    (job.root / 'runs/report.json').write_text('{"unfinished":', encoding='utf-8')
    with TestClient(create_app(tmp_path, worker_module=WORKER)) as client:
        assert client.get(f'/tasks/{job.id}').json()['state'] == 'interrupted'
        assert client.get(f'/tasks/{job.id}').json()['result'] is None
        assert client.get(f'/tasks/{job.id}/artifacts/report.json').status_code == 404
        assert client.get(f'/tasks/{job.id}/artifacts/patch.diff').status_code == 200


@pytest.mark.parametrize('kind', ['symlink', 'reparse'])
def test_issue_artifacts_refuse_linked_ancestor_even_with_regular_leaf(tmp_path, no_docker, monkeypatch, kind):
    job = seeded(tmp_path, 'cancelled')
    root = job.root / 'runs'
    if kind == 'symlink':
        original = Path.is_symlink
        monkeypatch.setattr(Path, 'is_symlink', lambda path: path == root or original(path))
    else:
        from types import SimpleNamespace

        original = Path.lstat
        monkeypatch.setattr(Path, 'lstat', lambda path: SimpleNamespace(st_file_attributes=1024,
                                                                     st_mode=original(path).st_mode)
                            if path == root else original(path))
    with pytest.raises(ValueError, match='Linked Issue artifacts'):
        issue_artifact_path(job, 'report.json')
    with TestClient(create_app(tmp_path, worker_module=WORKER)) as client:
        assert client.get(f'/tasks/{job.id}/artifacts/report.json').status_code == 404
        assert client.get(f'/tasks/{job.id}/artifacts/patch.diff').status_code == 404


def test_partial_report_never_uses_result_artifacts_pointer(tmp_path):
    job = seeded(tmp_path, 'cancelled')
    outside = tmp_path / 'unrelated'
    outside.mkdir()
    (outside / 'report.json').write_text('{"secret":"not-public"}', encoding='utf-8')
    (job.root / 'result.json').write_text(json.dumps({'artifacts': str(outside)}), encoding='utf-8')
    result = partial_issue_report(job, 'cancelled')
    assert result['status'] == 'cancelled' and 'secret' not in result
    with pytest.raises(ValueError, match='Unknown Issue artifact'):
        issue_artifact_path(job, '../report.json')


def _worker(path):
    report = public_progress(path.parent)
    (path.parent / 'fixture-started.json').write_text(json.dumps({
        'pid': os.getpid(), 'service_timeout': os.environ['CORECODER_SERVICE_TIMEOUT_SECONDS']}), encoding='utf-8')
    task_id = json.loads(path.read_text(encoding='utf-8'))['request']['task_id']
    if task_id.startswith('returned-'):
        report.update(status='task_timeout' if task_id == 'returned-timeout' else 'cancelled',
                      accepted=False, public_checks_passed=False, delivery_status='not_delivered')
        (path.parent / 'runs/report.json').write_text(json.dumps(report), encoding='utf-8')
        (path.parent / 'result.json').write_text(json.dumps(report), encoding='utf-8')
        return
    if task_id == 'fail-after-progress':
        raise SystemExit(3)
    time.sleep(60)


if __name__ == '__main__':
    _worker(Path(sys.argv[1]).resolve())
