"""Explicit offline integration: requires a prebuilt local image, never calls a model."""
import json
import os
import time

import pytest

from repairflow import checks
from sandbox import runner
from tests.repair_bundle_fixture import bundle

pytestmark = pytest.mark.skipif(os.environ.get('CORECODER_RUN_DOCKER_TESTS') != '1',
                                reason='Opt in with CORECODER_RUN_DOCKER_TESTS=1 and a local sandbox image')


def test_real_container_runs_public_and_private_checks(tmp_path, monkeypatch):
    monkeypatch.setenv('CORECODER_TEST_BACKEND', 'docker')
    task = bundle(tmp_path / 'sample')
    code = task / 'source/src/pkg/__init__.py'
    code.write_text(code.read_text().replace('x + 1', 'x + 2'), encoding='utf-8')
    for directory, names in [('public', ('Reproduce', 'Preserve')), ('grader', ('Target', 'Controls'))]:
        result = checks.groups(task / 'source', task / directory, 'pkg', 'src', tmp_path / directory, names)
        assert all(row['passed'] and row['sandbox']['network'] == 'none' for row in result.values())


def test_container_cannot_write_inputs_or_inherit_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'sentinel-not-a-real-key')
    source, harness, logs = (tmp_path / name for name in ('source', 'checks', 'logs'))
    for path in (source, harness, logs):
        path.mkdir()
    (source / 'input.txt').write_text('unchanged')
    boot = '''import json, os, pathlib, socket
assert 'DEEPSEEK_API_KEY' not in os.environ
assert not pathlib.Path('/app/.env').exists()
for target in ('/source/input.txt', '/checks/new.txt', '/etc/new.txt'):
    try:
        pathlib.Path(target).write_text('bad')
    except OSError:
        pass
    else:
        raise AssertionError('Writable input: ' + target)
sock = socket.socket()
sock.settimeout(1)
assert sock.connect_ex(('1.1.1.1', 443)) != 0
pathlib.Path('/tmp/result.json').write_text(json.dumps(dict(tests_run=1,successful=True,
    failures=0,errors=0,skipped=0,expected_failures=0,unexpected_successes=0)))
'''
    result = runner.run(source, harness, 'pkg', '.', logs, 'Target', boot, runner.preflight(), runner.owner(tmp_path))
    assert result['successful'] and (source / 'input.txt').read_text() == 'unchanged'


def test_real_replay_never_calls_a_provider(tmp_path, monkeypatch):
    from repairflow.engine import execute

    monkeypatch.setenv('CORECODER_TEST_BACKEND', 'docker')
    report = execute(bundle(tmp_path / 'sample'), 'replay', tmp_path / 'run')
    assert report['accepted'] and report['fresh_model_calls'] == 0
    assert report['sandbox']['backend'] == 'docker'


SCORE = """import json, pathlib
pathlib.Path('/tmp/result.json').write_text(json.dumps(dict(tests_run=1,successful=True,
    failures=0,errors=0,skipped=0,expected_failures=0,unexpected_successes=0)))
"""


def run_script(tmp_path, boot):
    source, harness, logs = (tmp_path / name for name in ('source', 'checks', 'logs'))
    for path in (source, harness, logs):
        path.mkdir()
    return runner.run(source, harness, 'pkg', '.', logs, 'Target', boot,
                      runner.preflight(), runner.owner(tmp_path))


@pytest.mark.parametrize('boot,status', [
    ('import time; time.sleep(60)', 'sandbox_timeout'),
    ('import os\nwhile True: os.write(1,b"x" * 8192)', 'sandbox_output_limit'),
    ('x = bytearray(2 * 1024 ** 3)', 'sandbox_oom'),
])
def test_real_resource_failures_stop_and_remove_container(tmp_path, boot, status):
    with pytest.raises(runner.SandboxError, match=status):
        run_script(tmp_path, boot)
    report = json.loads((tmp_path / 'logs/Target-sandbox.json').read_text())
    assert report['sandbox_status'] == status and not report.get('cleanup_failed')
    assert not runner.control(['ps', '-aq', '--filter', 'label=corecoder.sandbox.owner=' + runner.owner(tmp_path)]).strip()


def test_real_cgroup_limits_and_process_limit(tmp_path):
    boot = '''import pathlib, subprocess
def read(v2, v1):
    path = pathlib.Path('/sys/fs/cgroup/' + v2)
    return (path if path.exists() else pathlib.Path('/sys/fs/cgroup/' + v1)).read_text().strip()
assert read('memory.max','memory/memory.limit_in_bytes') == '1073741824'
assert read('pids.max','pids/pids.max') == '64'
if pathlib.Path('/sys/fs/cgroup/cpu.max').exists():
    quota, period = map(int, read('cpu.max','').split())
else:
    quota, period = int(read('unused','cpu/cpu.cfs_quota_us')), int(read('unused','cpu/cpu.cfs_period_us'))
assert quota == period
children = []
blocked = False
try:
    for _ in range(80):
        try:
            children.append(subprocess.Popen(['sleep','30']))
        except BlockingIOError:
            blocked = True
            break
finally:
    for child in children: child.kill()
    for child in children: child.wait()
assert blocked and len(children) < 64
'''
    assert run_script(tmp_path, boot + SCORE)['successful']


def test_api_cancel_removes_running_container(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from service.app import create_app
    from tests.test_service import wait

    registry = tmp_path / 'bundles'
    bundle(registry / 'sample')
    monkeypatch.setenv('CORECODER_TEST_BACKEND', 'docker')
    monkeypatch.setenv('CORECODER_REPAIR_BUNDLES', str(registry))
    root = tmp_path / 'service'
    with TestClient(create_app(root, timeout=60, worker_module='tests.sandbox_worker_stub')) as client:
        response = client.post('/tasks', json={'suite': 'repair', 'task_id': 'sample', 'mode': 'replay',
                                               'workflow': 'repair-approval-v1'})
        assert response.status_code == 202, response.text
        task_id = response.json()['id']
        job_root = root / task_id
        deadline = time.monotonic() + 20
        while not (job_root / 'sandbox-ready').exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (job_root / 'sandbox-ready').exists()
        client.post(f'/tasks/{task_id}/cancel').raise_for_status()
        assert wait(client, task_id)['state'] == 'cancelled'
    assert not runner.control(['ps', '-aq', '--filter', 'label=corecoder.sandbox.owner=' + runner.owner(job_root)]).strip()


def test_restart_removes_only_interrupted_task_container(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from service.app import create_app
    from tests.test_service_persistence import seed

    monkeypatch.setenv('CORECODER_TEST_BACKEND', 'docker')
    root = tmp_path / 'service'
    job = seed(root, state='running')
    from service.store import TaskStore

    job.request['workflow'] = 'repair-approval-v1'
    store = TaskStore(root)
    store.checkpoint(job)
    store.close()
    entry = tmp_path / 'runner.py'
    entry.write_text('pass')
    image = runner.preflight()['image_id']
    names = ['corecoder-test-restart-' + job.id, 'corecoder-test-other-' + job.id]
    try:
        for name, owned in zip(names, (job.root, tmp_path / 'unrelated')):
            runner.control(runner.command(image, name, runner.owner(owned), tmp_path, tmp_path, entry, '.', 'pkg', 'Target'))
            runner.control(['start', name])
        with TestClient(create_app(root)) as client:
            assert client.get('/tasks/' + job.id).json()['state'] == 'interrupted'
        assert not runner.control(['ps', '-aq', '--filter', 'name=^/' + names[0] + '$']).strip()
        assert runner.control(['ps', '-q', '--filter', 'name=^/' + names[1] + '$']).strip()
    finally:
        runner.control(['rm', '-f', *names])
