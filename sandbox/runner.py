"""One disposable, offline container per test group. No model credentials enter it."""
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
import threading
import time
import uuid
from contextvars import ContextVar
from pathlib import Path

ACTIVE_POLICY = ContextVar('repair_sandbox_policy', default=None)
RUNNER_START_MARKER = b'CORECODER_SANDBOX_RUNNER_STARTED\n'


class SandboxError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(status)


def backend():
    value = os.environ.get('CORECODER_TEST_BACKEND', 'docker')
    if value not in {'docker', 'local'}:
        raise ValueError('CORECODER_TEST_BACKEND must be docker or local')
    return value


def owner(root):
    return hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()


def control(args, timeout=30):
    try:
        result = subprocess.run(['docker', *args], capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SandboxError('sandbox_unavailable') from exc
    if result.returncode:
        raise SandboxError('sandbox_control_failed')
    return result.stdout


def preflight(image=None):
    image = image or os.environ.get('CORECODER_SANDBOX_IMAGE', 'corecoder-test-sandbox:v1')
    try:
        info = json.loads(control(['info', '--format', '{{json .OSType}}']))
    except SandboxError as exc:
        raise SandboxError('sandbox_unavailable') from exc
    if info != 'linux':
        raise SandboxError('sandbox_requires_linux_containers')
    try:
        metadata = json.loads(control(['image', 'inspect', image]))[0]
    except SandboxError as exc:
        raise SandboxError('sandbox_image_missing') from exc
    # Use the immutable local content ID; never pull at test execution time.
    image_id = metadata['Id']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
        raise SandboxError('sandbox_invalid_image')
    return {'backend': 'docker', 'image': image, 'image_id': image_id,
            'network': 'none', 'cpus': 1, 'memory_bytes': 1073741824, 'pids': 64,
            'output_limit_bytes': 1048576}


def cleanup(root):
    """Only remove containers owned by this exact task, never unrelated containers."""
    ids = control(['ps', '-aq', '--filter', 'label=corecoder.sandbox.owner=' + owner(root)]).decode().split()
    if ids:
        control(['rm', '-f', *ids])


def bounded(args, timeout, limit=1048576, *, input_data=None):
    """Drain output while feeding trusted stdin; timeout also bounds blocked input."""
    if input_data is not None and not isinstance(input_data, bytes):
        raise TypeError('Docker stdin must be bytes')
    proc = subprocess.Popen(['docker', *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL)
    buffers = [bytearray(), bytearray()]
    total = 0
    exceeded = threading.Event()
    lock = threading.Lock()

    def stop():
        try:
            proc.kill()
        except OSError:  # It can exit between the output reader and timeout handler.
            pass

    def drain(stream, index):
        nonlocal total
        while chunk := stream.read(8192):
            with lock:
                room = max(0, limit - total)
                buffers[index].extend(chunk[:room])
                total += len(chunk)
                if total > limit:
                    exceeded.set()
                    stop()

    def feed():
        try:
            proc.stdin.write(input_data)
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass  # The command's exit status/output still describe an early exit.
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    threads = [threading.Thread(target=drain, args=(stream, i), daemon=True)
               for i, stream in enumerate((proc.stdout, proc.stderr))]
    for thread in threads:
        thread.start()
    if input_data is not None:
        writer = threading.Thread(target=feed, daemon=True)
        threads.append(writer)
        writer.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop()
        proc.wait()
    finally:
        for thread in threads:
            thread.join(5)
        for stream in (proc.stdout, proc.stderr):
            stream.close()
    return proc.returncode, bytes(buffers[0]), bytes(buffers[1]), timed_out, exceeded.is_set()


def parse_archive(raw):
    """Read one small regular file without extracting any archive paths or links."""
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        members = archive.getmembers()
        if (len(members) != 1 or not members[0].isfile() or members[0].name != 'result.json'
                or members[0].size > 65536):
            raise ValueError('Invalid result archive')
        score = json.loads(archive.extractfile(members[0]).read())
    counts = ('tests_run', 'skipped', 'expected_failures', 'unexpected_successes', 'errors', 'failures')
    if (not isinstance(score, dict) or type(score.get('successful')) is not bool
            or any(type(score.get(k)) is not int or score[k] < 0 for k in counts)):
        raise ValueError('Invalid test result')
    return {key: score[key] for key in (*counts, 'successful')}


def command(image_id, name, task_owner, source, harness, entry, source_root, package, group):
    relative = Path(source_root)
    if relative.is_absolute() or source_root.startswith('/') or '..' in relative.parts or '\\' in source_root or ':' in source_root:
        raise ValueError('Unsafe source root')
    mounts = []
    # A generated single-file bind mount can become unreadable on Desktop/WSL.
    # Keep source/checks read-only; transmit the trusted runner through stdin.
    for path, target in ((source, '/source'), (harness, '/checks')):
        path = Path(path).resolve()
        if ',' in str(path):
            raise ValueError('Comma in Docker mount path')
        mounts += ['--mount', f'type=bind,source={path},target={target},readonly']
    return ['create', '--name', name, '--label', 'corecoder.sandbox.owner=' + task_owner,
            '--network', 'none', '--user', '10001:10001', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--cpus', '1', '--memory', '1g', '--memory-swap', '1g',
            '--pids-limit', '64', '--init', '--log-driver', 'none',
            '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m,mode=1777', '--workdir', '/source',
            '--env', 'PYTHONDONTWRITEBYTECODE=1', '--env', 'PYTHONIOENCODING=utf-8',
            '--pull', 'never', *mounts, image_id, 'python', '-I', '-B', '-c',
            'import time; time.sleep(300)']


def run(source, harness, package, source_root, logs, group, boot, policy, task_owner):
    name = 'corecoder-test-' + uuid.uuid4().hex
    entry = logs / (group + '-runner.py')
    code_text = ('import os, signal\nsignal.alarm(15)\n'
                 f'os.write(2, {RUNNER_START_MARKER!r})\n' + boot)
    runner_input = code_text.encode('utf-8')
    entry.write_bytes(runner_input)  # Evidence only; this path is never mounted.
    started = time.perf_counter()
    result = {'returncode': None, 'timed_out': False, 'sandbox': dict(policy),
              'sandbox_status': 'sandbox_start_failed', 'phase': 'create',
              'runner_transport': 'stdin', 'runner_sha256': hashlib.sha256(runner_input).hexdigest(),
              'runner_bytes': len(runner_input), 'runner_started': False, 'result_collected': False}
    try:
        control(command(policy['image_id'], name, task_owner, source, harness, entry, source_root, package, group))
        # Keep tmpfs mounted until results have been copied. A stopped container
        # loses /tmp even though its readonly root filesystem still exists.
        result['phase'] = 'start'
        control(['start', name])
        result['phase'] = 'execute'
        code, out, err, timeout, overflow = bounded(['exec', '-i', name, 'python', '-I', '-B', '-',
                                                   '/source/' + source_root, '/checks', package,
                                                   group, '/tmp/result.json'], 20, input_data=runner_input)
        (logs / (group + '.stdout.txt')).write_bytes(out)
        (logs / (group + '.stderr.txt')).write_bytes(err)
        # Diagnostic only, never an attestation of candidate/test correctness.
        result['runner_started'] = err.startswith(RUNNER_START_MARKER)
        result['phase'] = 'inspect'
        state = json.loads(control(['inspect', '--format', '{{json .State}}', name]))
        timeout = timeout or code == 142  # SIGALRM: original 15-second test deadline.
        oom = state.get('OOMKilled', False)
        if code == 137 and state.get('Running'):
            _, memory, _, _, _ = bounded(['exec', name, 'cat', '/sys/fs/cgroup/memory.events'], 5, 4096)
            oom = oom or any(line.startswith(b'oom_kill ') and int(line.split()[1]) > 0 for line in memory.splitlines())
        result.update(returncode=code, timed_out=timeout,
                      sandbox_status='sandbox_timeout' if timeout else 'sandbox_output_limit' if overflow
                      else 'sandbox_oom' if oom else 'sandbox_runner_start_failed'
                      if not result['runner_started'] else 'completed')
        if result['sandbox_status'] == 'completed':
            # Docker's archive API does not expose this tmpfs mount. Stream
            # the one result file while the container is alive instead.
            result['phase'] = 'collect_result'
            copy_code, archive, copy_err, copy_timeout, copy_overflow = bounded(
                ['exec', name, 'tar', '-C', '/tmp', '-cf', '-', 'result.json'], 10, 131072)
            (logs / (group + '-result.stderr.txt')).write_bytes(copy_err)
            result['result_read'] = {'returncode': copy_code, 'timed_out': copy_timeout,
                                     'output_limit_exceeded': copy_overflow}
            if copy_timeout:
                result['sandbox_status'] = 'sandbox_result_timeout'
            elif copy_overflow:
                result['sandbox_status'] = 'sandbox_invalid_result'
            elif copy_code:
                result['sandbox_status'] = 'sandbox_result_missing'
            else:
                try:
                    score = parse_archive(archive)
                    result.update(score, result_collected=True)
                    (logs / (group + '.json')).write_text(json.dumps(score), encoding='utf-8')
                except (ValueError, KeyError, TypeError, AttributeError, tarfile.TarError, UnicodeError):
                    result['sandbox_status'] = 'sandbox_invalid_result'
        else:
            result['phase'] = 'execute'
    except SandboxError as exc:
        result['sandbox_status'] = exc.status
    finally:
        if result['sandbox_status'] != 'completed':
            result['failure_phase'] = result['phase']
        try:
            control(['rm', '-f', name])
        except SandboxError:
            result['cleanup_failed'] = True
            result['status_before_cleanup'] = result['sandbox_status']
            result['sandbox_status'] = 'sandbox_cleanup_failed'
        result['seconds'] = round(time.perf_counter() - started, 4)
        (logs / (group + '-sandbox.json')).write_text(json.dumps(result), encoding='utf-8')
    if result['sandbox_status'] != 'completed':
        raise SandboxError(result['sandbox_status'])
    return result
