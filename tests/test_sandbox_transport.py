"""Exercise runner transport without Docker, host mounts, or model calls."""

import hashlib
import io
import json
import subprocess
import sys
import tarfile

import pytest

from sandbox import runner


def child_process(monkeypatch, script):
    """Run an ordinary Python child behind the Docker CLI subprocess boundary."""
    real_popen = subprocess.Popen
    calls = []

    def popen(args, **kwargs):
        calls.append((args, kwargs))
        return real_popen([sys.executable, '-I', '-B', '-c', script], **kwargs)

    monkeypatch.setattr(runner.subprocess, 'Popen', popen)
    return calls


def test_large_stdin_and_both_output_streams_do_not_deadlock(monkeypatch):
    size = 524288
    payload = bytes(range(256)) * 8192
    child_process(monkeypatch, f'''
import hashlib
import sys
sys.stdout.buffer.write(b'o' * {size})
sys.stdout.buffer.flush()
sys.stderr.buffer.write(b'e' * {size})
sys.stderr.buffer.flush()
payload = sys.stdin.buffer.read()
sys.stdout.buffer.write(hashlib.sha256(payload).hexdigest().encode())
''')
    code, out, err, timeout, overflow = runner.bounded(
        ['exec', '-i', 'unused'], 10, 2 * size + 1024, input_data=payload)

    assert code == 0 and not timeout and not overflow
    assert out == b'o' * size + hashlib.sha256(payload).hexdigest().encode()
    assert err == b'e' * size


@pytest.mark.filterwarnings('error::pytest.PytestUnhandledThreadExceptionWarning')
def test_child_closing_stdin_does_not_turn_exit_into_transport_error(monkeypatch):
    child_process(monkeypatch, '''
import os
import sys
os.close(0)
sys.stdout.write('closed')
''')
    code, out, err, timeout, overflow = runner.bounded(
        ['exec', '-i', 'unused'], 10, input_data=b'x' * 4194304)

    assert code == 0 and out == b'closed' and err == b''
    assert not timeout and not overflow


def test_timeout_stops_child_while_input_writer_is_blocked(monkeypatch):
    child_process(monkeypatch, '''
import sys
import time
sys.stdout.write('ready')
sys.stdout.flush()
time.sleep(30)
''')
    code, out, _, timeout, overflow = runner.bounded(
        ['exec', '-i', 'unused'], 0.5, input_data=b'x' * 4194304)

    assert code != 0 and timeout and not overflow
    assert out == b'ready'


def test_output_limit_stops_child_and_blocked_input_writer(monkeypatch):
    child_process(monkeypatch, '''
import sys
sys.stdout.buffer.write(b'x' * 4194304)
sys.stdout.buffer.flush()
sys.stdin.buffer.read()
''')
    code, out, err, timeout, overflow = runner.bounded(
        ['exec', '-i', 'unused'], 10, 4096, input_data=b'y' * 4194304)

    assert code != 0 and overflow and not timeout
    assert len(out) + len(err) <= 4096


def test_no_input_preserves_devnull_and_empty_input_delivers_eof(monkeypatch):
    calls = child_process(monkeypatch, 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read() or b"eof")')
    for payload in (None, b''):
        code, out, err, timeout, overflow = runner.bounded(['unused'], 10, input_data=payload)
        assert (code, out, err, timeout, overflow) == (0, b'eof', b'', False, False)
    assert calls[0][1]['stdin'] == subprocess.DEVNULL
    assert calls[1][1]['stdin'] == subprocess.PIPE


def test_runner_is_not_a_single_file_bind_mount(tmp_path):
    args = runner.command('sha256:' + 'a' * 64, 'task', 'owner', tmp_path / 'source', tmp_path / 'checks',
                          tmp_path / 'runner.py', 'src', 'pkg', 'Target')
    mounts = [args[index + 1] for index, argument in enumerate(args) if argument == '--mount']

    assert len(mounts) == 2
    assert {mount.split('target=')[1].split(',')[0] for mount in mounts} == {'/source', '/checks'}
    assert all(mount.endswith(',readonly') for mount in mounts)
    assert not any('runner.py' in argument for argument in args)


def result_archive(successful=True):
    score = {'tests_run': 1, 'successful': successful, 'skipped': 0, 'expected_failures': 0,
             'unexpected_successes': 0, 'errors': 0, 'failures': int(not successful)}
    body = json.dumps(score).encode()
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        member = tarfile.TarInfo('result.json')
        member.size = len(body)
        archive.addfile(member, io.BytesIO(body))
    return output.getvalue(), score


def fake_container(monkeypatch, execution=None, collection=None, *, oom=False):
    calls = []
    execution = execution or (0, b'test output', runner.RUNNER_START_MARKER, False, False)
    if collection is None:
        collection = (0, result_archive()[0], b'', False, False)

    def control(args, *unused):
        calls.append(('control', args, None))
        if args[0] == 'inspect':
            return json.dumps({'OOMKilled': oom, 'Running': False}).encode()
        return b''

    def bounded(args, timeout, limit=1048576, *, input_data=None):
        calls.append(('bounded', args, input_data))
        return collection if 'tar' in args else execution

    monkeypatch.setattr(runner, 'control', control)
    monkeypatch.setattr(runner, 'bounded', bounded)
    return calls


def run_example(tmp_path):
    return runner.run(tmp_path / 'source', tmp_path / 'checks', 'pkg', 'src', tmp_path,
                      'Target', 'print("trusted bootstrap")\n', {'image_id': 'pinned-image'}, 'owner')


def test_stdin_payload_is_exactly_the_archived_trusted_runner(tmp_path, monkeypatch):
    calls = fake_container(monkeypatch)
    result = run_example(tmp_path)
    executions = [call for call in calls if call[0] == 'bounded' and 'python' in call[1]]
    assert len(executions) == 1
    _, args, payload = executions[0]
    assert args[:2] == ['exec', '-i']
    assert args[args.index('python'):] == [
        'python', '-I', '-B', '-', '/source/src', '/checks', 'pkg', 'Target', '/tmp/result.json']
    assert payload == (tmp_path / 'Target-runner.py').read_bytes()
    assert b'print("trusted bootstrap")' in payload
    assert payload.index(b'os.write(2,') < payload.index(b'print("trusted bootstrap")')
    assert result['runner_transport'] == 'stdin'
    assert result['runner_sha256'] == hashlib.sha256(payload).hexdigest()
    assert result['runner_bytes'] == len(payload)
    assert result['runner_started'] and result['result_collected']
    assert calls[-1][1][:2] == ['rm', '-f']


@pytest.mark.parametrize('execution,collection,oom,status,phase', [
    ((2, b'', b'python: input error', False, False), None, False,
     'sandbox_runner_start_failed', 'execute'),
    ((2, b'', b'candidate output\n' + runner.RUNNER_START_MARKER, False, False), None, False,
     'sandbox_runner_start_failed', 'execute'),
    ((-9, b'', b'', True, False), None, False, 'sandbox_timeout', 'execute'),
    ((-9, b'', b'', False, True), None, False, 'sandbox_output_limit', 'execute'),
    ((137, b'', b'', False, False), None, True, 'sandbox_oom', 'execute'),
    ((142, b'', b'', False, False), None, False, 'sandbox_timeout', 'execute'),
    (None, (2, b'', b'tar: result.json missing', False, False), False,
     'sandbox_result_missing', 'collect_result'),
    (None, (0, b'not a tar archive', b'archive diagnostic', False, False), False,
     'sandbox_invalid_result', 'collect_result'),
    (None, (-9, b'', b'collection stalled', True, False), False,
     'sandbox_result_timeout', 'collect_result'),
    (None, (-9, b'x' * 64, b'collection overflow', False, True), False,
     'sandbox_invalid_result', 'collect_result'),
])
def test_failure_phase_and_raw_evidence_are_preserved(tmp_path, monkeypatch, execution, collection, oom, status, phase):
    calls = fake_container(monkeypatch, execution, collection, oom=oom)
    with pytest.raises(runner.SandboxError) as failure:
        run_example(tmp_path)
    assert failure.value.status == status
    result = json.loads((tmp_path / 'Target-sandbox.json').read_text(encoding='utf-8'))
    assert result['sandbox_status'] == status and result['failure_phase'] == phase
    assert result['result_collected'] is False
    assert result['returncode'] == (execution[0] if execution is not None else 0)
    assert calls[-1][1][:2] == ['rm', '-f']
    collections = [call for call in calls if call[0] == 'bounded' and 'tar' in call[1]]
    assert len(collections) == int(phase == 'collect_result')
    if phase == 'collect_result':
        assert (tmp_path / 'Target-result.stderr.txt').read_bytes() == collection[2]
        assert result['result_read']['returncode'] == collection[0]
    else:
        assert 'result_read' not in result


def test_valid_test_failure_is_completed_execution_not_sandbox_failure(tmp_path, monkeypatch):
    archive, score = result_archive(successful=False)
    fake_container(monkeypatch, (1, b'assertion failed', runner.RUNNER_START_MARKER, False, False),
                   (0, archive, b'', False, False))
    result = run_example(tmp_path)

    assert result['sandbox_status'] == 'completed'
    assert result['returncode'] == 1 and result['result_collected']
    assert result['successful'] is False and result['failures'] == 1
    assert json.loads((tmp_path / 'Target.json').read_text(encoding='utf-8')) == score
