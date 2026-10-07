"""Offline Docker/Linux acceptance in an isolated Compose project and data volume."""

import argparse
import json
import os
import socket
import subprocess
import time
import uuid
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent.parent
TERMINAL = {'succeeded', 'failed', 'cancelled', 'timed_out', 'interrupted'}


class Acceptance:
    def __init__(self, output):
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.project = 'corecoder-acceptance-' + uuid.uuid4().hex[:10]
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            self.port = listener.getsockname()[1]
        self.env = dict(os.environ, CORECODER_PORT=str(self.port), CORECODER_IMAGE='corecoder-local:dev')
        self.report = {'project': self.project, 'port': self.port, 'checks': {}, 'status': 'running', 'commands': []}
        self.started = False
        self.faults = False
        self.http = build_opener(ProxyHandler({}))

    def command(self, argv, timeout=120):
        record = {'argv': argv}
        self.report['commands'].append(record)
        try:
            result = subprocess.run(argv, cwd=ROOT, env=self.env, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=timeout, check=False)
            record.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
            if result.returncode:
                raise RuntimeError(f'Command failed: {argv[0:3]} (see acceptance report)')
            return result.stdout
        except subprocess.TimeoutExpired as exc:
            record.update(error='timeout', timeout=timeout)
            raise RuntimeError(f'Command timed out after {timeout}s: {argv[0:3]}') from exc

    def compose(self, *args, timeout=120):
        files = ['-f', 'deploy/compose.yaml']
        if self.faults:
            files += ['-f', 'deploy/compose.acceptance.yaml']
        return self.command(['docker', 'compose', '-p', self.project, *files, *args], timeout)

    def request(self, route, body=None, key=None, raw=False):
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Idempotency-Key'] = key
        request = Request(f'http://127.0.0.1:{self.port}{route}',
                          data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with self.http.open(request, timeout=5) as response:
            content = response.read().decode('utf-8')
            return content if raw else json.loads(content)

    def wait(self, task_id, states=TERMINAL):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            row = self.request(f'/tasks/{task_id}')
            if row['state'] in states:
                return row
            time.sleep(0.1)
        raise RuntimeError('Task state did not become ready')

    def verify(self, label, value):
        self.report['checks'][label] = bool(value)
        if not value:
            raise RuntimeError(f'Acceptance failed: {label}')

    def run(self):
        self.command(['docker', 'info', '--format', '{{.ServerVersion}}'], timeout=15)
        self.compose('config', '--quiet', timeout=15)
        self.command(['docker', 'build', '--target', 'validation', '-t', 'corecoder-local:validation',
                      '-f', 'deploy/Dockerfile', '.'], timeout=600)
        self.command(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                      '--tmpfs', '/tmp:rw,mode=1777',
                      '--tmpfs', '/app/tests/.pytest_tmp:rw,uid=10001,gid=10001,mode=0700',
                      'corecoder-local:validation', 'python', '-m', 'pytest', 'tests/test_service.py',
                      'tests/test_service_persistence.py', 'tests/test_code_knowledge_mcp.py', 'tests/test_mcp.py',
                      'tests/test_local_deploy_acceptance.py',
                      'tests/test_workflow.py',
                      '-q', '-p', 'no:cacheprovider', '--basetemp=/tmp/pytest'], timeout=180)
        self.report['checks']['linux_service_and_mcp_tests'] = True
        self.command(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--tmpfs', '/tmp:rw,mode=1777',
                      'corecoder-local:validation', 'python', '-m', 'mcp_servers.demo',
                      '--workspace', '/app/evals/fixtures/timeout-units/workspace', '--query', 'timeout'])
        self.report['checks']['mcp_stdio_demo'] = True
        self.started = True
        self.compose('up', '-d', '--build', '--wait', '--wait-timeout', '60', timeout=600)
        body = {'task_id': 'timeout-units', 'mode': 'scripted'}
        task_id = self.request('/tasks', body, key='container-scripted')['id']
        good = self.wait(task_id)
        self.verify('scripted_independent_verification', good['state'] == 'succeeded' and good['result']['verification']['passed'])
        patch = self.request(f'/tasks/{task_id}/artifacts/patch.diff', raw=True)
        self.verify('patch_download', '---' in patch)
        self.verify('idempotent_submit', self.request('/tasks', body, key='container-scripted')['id'] == task_id)
        bad_id = self.request('/tasks', {'task_id': 'timeout-units', 'mode': 'unchanged'})['id']
        self.verify('unchanged_rejected', self.wait(bad_id)['state'] == 'failed')
        self.compose('restart', 'repair')
        self.compose('up', '-d', '--wait', '--wait-timeout', '60')
        self.verify('restart_preserves_result', self.request(f'/tasks/{task_id}') == good)
        self.verify('restart_preserves_patch', self.request(f'/tasks/{task_id}/artifacts/patch.diff', raw=True) == patch)
        self.verify('restart_preserves_idempotency', self.request('/tasks', body, key='container-scripted')['id'] == task_id)
        self.verify('sse_persisted', 'id: 3' in self.request(f'/tasks/{task_id}/events', raw=True))
        graph_body = {'task_id': 'timeout-units', 'mode': 'scripted', 'workflow': 'langgraph-v1'}
        graph_id = self.request('/tasks', graph_body, key='container-graph')['id']
        self.verify('graph_independent_verification', self.wait(graph_id)['state'] == 'succeeded')
        graph_snapshot = self.request(f'/tasks/{graph_id}/artifacts/workflow.json')
        self.verify('graph_snapshot', graph_snapshot['outcome'] == 'accepted')
        self.verify('graph_idempotency', self.request('/tasks', graph_body, key='container-graph')['id'] == graph_id)
        self.compose('down')
        self.faults = True
        self.compose('up', '-d', '--wait', '--wait-timeout', '60')
        cancelled = self.request('/tasks', {'task_id': 'timeout-units', 'mode': 'unchanged'})['id']
        self.wait(cancelled, {'running'})
        self.request(f'/tasks/{cancelled}/cancel', {})
        self.verify('running_cancel', self.wait(cancelled)['state'] == 'cancelled')
        interrupted = self.request('/tasks', {'task_id': 'timeout-units', 'mode': 'unchanged'}, key='crash')['id']
        self.wait(interrupted, {'running'})
        self.compose('kill', '-s', 'SIGKILL', 'repair')
        self.compose('up', '-d', '--wait', '--wait-timeout', '60')
        self.verify('hard_kill_marks_interrupted', self.wait(interrupted)['state'] == 'interrupted')
        self.verify('hard_kill_does_not_retry', self.request('/tasks', {'task_id': 'timeout-units', 'mode': 'unchanged'}, key='crash')['id'] == interrupted)
        self.report['image'] = json.loads(self.command(['docker', 'image', 'inspect', 'corecoder-local:validation']))[0]['Id']
        self.report['dependencies'] = self.command(['docker', 'run', '--rm', 'corecoder-local:validation', 'python', '-m', 'pip', 'freeze'])
        self.report['status'] = 'passed'

    def finish(self):
        if self.started:
            for args, timeout in [(('logs', '--no-color'), 20), (('down',), 60)]:
                try:
                    self.compose(*args, timeout=timeout)
                except (RuntimeError, OSError) as exc:
                    self.report.setdefault('cleanup_errors', []).append(str(exc))
                    self.report['status'] = 'failed'
        self.report['retained_volume'] = self.project + '_task-data' if self.started else None
        (self.output / 'acceptance.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.tmp/deploy-acceptance' / uuid.uuid4().hex[:10])
    args = parser.parse_args()
    acceptance = Acceptance(args.output)
    try:
        acceptance.run()
    except (RuntimeError, OSError) as exc:
        acceptance.report.update(status='failed', error=str(exc))
    finally:
        acceptance.finish()
    print(acceptance.output / 'acceptance.json')
    print(acceptance.report['status'])
    if acceptance.report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
