"""Explicit offline integration: requires a prebuilt local image, never calls a model."""
import os

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
