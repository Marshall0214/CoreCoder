import io
import json
import tarfile

import pytest

from sandbox import runner


def archive(score, name='result.json', kind=tarfile.REGTYPE):
    data = json.dumps(score).encode()
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w') as stream:
        entry = tarfile.TarInfo(name)
        entry.type, entry.size = kind, len(data) if kind == tarfile.REGTYPE else 0
        stream.addfile(entry, io.BytesIO(data))
    return raw.getvalue()


def score():
    return {'tests_run': 1, 'successful': True, 'skipped': 0, 'expected_failures': 0,
            'unexpected_successes': 0, 'errors': 0, 'failures': 0}


def test_default_fail_closed_before_provider(tmp_path, monkeypatch):
    from repairflow.engine import execute
    from tests.repair_bundle_fixture import bundle

    task = bundle(tmp_path / 'sample')
    monkeypatch.delenv('CORECODER_TEST_BACKEND', raising=False)
    monkeypatch.setattr(runner, 'preflight', lambda: (_ for _ in ()).throw(runner.SandboxError('sandbox_unavailable')))
    with pytest.raises(runner.SandboxError, match='sandbox_unavailable'):
        execute(task, 'replay', tmp_path / 'run', provider_factory=lambda _: pytest.fail('Model called'))
    assert not (tmp_path / 'run').exists()


def test_policy_does_not_inherit_keys_or_host_network(tmp_path):
    args = runner.command('sha256:' + 'a' * 64, 'test', 'owner', tmp_path, tmp_path,
                          tmp_path / 'runner.py', 'src', 'pkg', 'Target')
    assert args[args.index('--network') + 1] == 'none'
    assert args[args.index('--user') + 1] == '10001:10001'
    assert '--read-only' in args and '--privileged' not in args
    assert args[args.index('--memory-swap') + 1] == '1g'
    assert all('readonly' in args[i + 1] for i, value in enumerate(args) if value == '--mount')
    assert not any('API_KEY' in value or 'docker.sock' in value for value in args)


@pytest.mark.parametrize('root', ['../escape', '/root', 'C:/secret', 'src\\escape'])
def test_source_root_cannot_escape(tmp_path, root):
    with pytest.raises(ValueError):
        runner.command('id', 'test', 'owner', tmp_path, tmp_path, tmp_path, root, 'pkg', 'Target')


def test_result_archive_is_not_extracted():
    assert runner.parse_archive(archive(score())) == score()
    for name, kind in [('../result.json', tarfile.REGTYPE), ('result.json', tarfile.SYMTYPE)]:
        with pytest.raises(ValueError):
            runner.parse_archive(archive(score(), name, kind))
    invalid = score()
    invalid['tests_run'] = True
    with pytest.raises(ValueError):
        runner.parse_archive(archive(invalid))


def test_preflight_pins_local_image(monkeypatch):
    def control(args):
        return b'"linux"' if args[0] == 'info' else json.dumps([{'Id': 'sha256:' + 'a' * 64}]).encode()
    monkeypatch.setattr(runner, 'control', control)
    assert runner.preflight()['image_id'] == 'sha256:' + 'a' * 64


def test_cleanup_only_exact_owner(tmp_path, monkeypatch):
    calls = []

    def control(args):
        calls.append(args)
        return b'abc\ndef' if args[0] == 'ps' else b''
    monkeypatch.setattr(runner, 'control', control)
    runner.cleanup(tmp_path)
    assert calls == [['ps', '-aq', '--filter', 'label=corecoder.sandbox.owner=' + runner.owner(tmp_path)],
                     ['rm', '-f', 'abc', 'def']]


@pytest.mark.parametrize('script,timeout,limit,index', [
    ('import time; time.sleep(10)', 0.1, 1024, 3),
    ('import sys; sys.stdout.write("x" * 1000000)', 5, 1024, 4)])
def test_bounded_streams_stop_hang_and_flood(monkeypatch, script, timeout, limit, index):
    import subprocess
    import sys

    real = subprocess.Popen
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda args, **kw: real([sys.executable, '-c', script], **kw))
    result = runner.bounded(['unused'], timeout, limit)
    assert result[index] and len(result[1]) + len(result[2]) <= limit


@pytest.mark.parametrize('timeout,overflow,oom,status', [
    (True, False, False, 'sandbox_timeout'), (False, True, False, 'sandbox_output_limit'),
    (False, False, True, 'sandbox_oom'), (False, False, False, 'completed')])
def test_execution_classification_and_cleanup(tmp_path, monkeypatch, timeout, overflow, oom, status):
    calls = []

    def control(args):
        calls.append(args)
        return json.dumps({'ExitCode': 0, 'OOMKilled': oom}).encode() if args[0] == 'inspect' else b''

    def bounded(args, *unused):
        if args[0] == 'cp':
            return 0, archive(score()), b'', False, False
        return 0, b'output', b'', timeout, overflow
    monkeypatch.setattr(runner, 'control', control)
    monkeypatch.setattr(runner, 'bounded', bounded)
    kwargs = (tmp_path, tmp_path, 'pkg', 'src', tmp_path, 'Target', 'pass', {'image_id': 'id'}, 'owner')
    if status == 'completed':
        assert runner.run(*kwargs)['tests_run'] == 1
    else:
        with pytest.raises(runner.SandboxError, match=status):
            runner.run(*kwargs)
    assert calls[-1][:2] == ['rm', '-f']
    assert json.loads((tmp_path / 'Target-sandbox.json').read_text())['sandbox_status'] == status
