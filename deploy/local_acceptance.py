"""Real HTTP restart/crash acceptance, independent of Docker and real models."""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil

from deploy.acceptance import ROOT, Acceptance


class LocalAcceptance(Acceptance):
    def __init__(self, output):
        super().__init__(output)
        self.data = self.output / 'data'
        if self.data.exists():
            raise ValueError('Output already contains task data; choose a fresh directory')
        self.process = None
        self.streams = []
        self.workers = []
        self.report.update(platform=platform.platform(), python=sys.version, kind='host-http', servers=[], tasks={})

    def start_server(self, faults=False):
        sequence = len(self.report['servers']) + 1
        stdout = (self.output / f'server-{sequence}.stdout.txt').open('wb')
        stderr = (self.output / f'server-{sequence}.stderr.txt').open('wb')
        self.streams.extend([stdout, stderr])
        argv = [sys.executable, '-m', 'deploy.local_server', '--data', str(self.data), '--port', str(self.port)]
        if faults:
            argv.append('--faults')
        options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
        self.process = subprocess.Popen(argv, cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING='utf-8'),
                                        stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, **options)
        self.report['servers'].append({'pid': self.process.pid, 'faults': faults, 'argv': argv})
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('Acceptance server exited during startup; inspect server logs')
            try:
                if self.request('/health') == {'status': 'ok'}:
                    return
            except OSError:
                pass
            time.sleep(0.1)
        raise RuntimeError('Acceptance server did not become ready')

    def stop_server(self, hard=False):
        if self.process is None:
            return
        try:
            if self.process.poll() is None:
                if hard:
                    self.process.kill()  # Only the Popen server owned by this harness; preserve its workers for recovery.
                else:
                    self.request('/__acceptance__/shutdown', {})
                self.process.wait(timeout=20)
            self.report['servers'][-1].update(returncode=self.process.returncode, hard_stop=hard)
        finally:
            if self.process.poll() is not None:
                self.process = None

    @staticmethod
    def alive(identity):
        try:
            process = psutil.Process(identity['pid'])
            return abs(process.create_time() - identity['created_at']) < 0.001 and process.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    def capture_workers(self, task_id):
        deadline = time.monotonic() + 10
        path = self.data / task_id / 'pids.json'
        while time.monotonic() < deadline:
            try:
                pids = json.loads(path.read_text(encoding='utf-8'))
                identities = [{'pid': pid, 'created_at': psutil.Process(pid).create_time()} for pid in pids]
                self.workers.extend(identities)
                self.report['tasks'][task_id] = {'worker_identities': identities}
                return identities
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.03)
        raise RuntimeError('Worker did not actually start its child process')

    def children_stopped(self, identities):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if all(not self.alive(identity) for identity in identities):
                return True
            time.sleep(0.05)
        return False

    def run(self):
        self.start_server()
        body = {'task_id': 'timeout-units', 'mode': 'scripted'}
        task_id = self.request('/tasks', body, key='host-scripted')['id']
        good = self.wait(task_id)
        self.report['tasks'][task_id] = good
        self.verify('scripted_independent_verification', good['state'] == 'succeeded' and good['result']['verification']['passed'])
        bad_id = self.request('/tasks', {'task_id': 'timeout-units', 'mode': 'unchanged'})['id']
        self.verify('unchanged_rejected', self.wait(bad_id)['state'] == 'failed')
        patch = self.request(f'/tasks/{task_id}/artifacts/patch.diff', raw=True)
        self.verify('patch_download', '---' in patch)
        self.verify('idempotent_submit', self.request('/tasks', body, key='host-scripted')['id'] == task_id)
        self.stop_server()
        self.start_server()
        self.verify('restart_preserves_result', self.request(f'/tasks/{task_id}') == good)
        self.verify('restart_preserves_patch', self.request(f'/tasks/{task_id}/artifacts/patch.diff', raw=True) == patch)
        self.verify('restart_preserves_idempotency', self.request('/tasks', body, key='host-scripted')['id'] == task_id)
        self.verify('restart_preserves_sse', 'id: 3' in self.request(f'/tasks/{task_id}/events', raw=True))
        self.stop_server()
        self.start_server(faults=True)
        long_task = {'task_id': 'timeout-units', 'mode': 'unchanged'}
        cancelled = self.request('/tasks', long_task)['id']
        identities = self.capture_workers(cancelled)
        self.request(f'/tasks/{cancelled}/cancel', {})
        self.verify('running_cancel', self.wait(cancelled)['state'] == 'cancelled')
        self.verify('cancel_stops_worker_and_child', self.children_stopped(identities))
        interrupted = self.request('/tasks', long_task, key='host-crash')['id']
        identities = self.capture_workers(interrupted)
        queued = self.request('/tasks', body, key='host-queued')['id']
        self.verify('task_really_queued', self.request(f'/tasks/{queued}')['state'] == 'queued')
        self.stop_server(hard=True)
        self.verify('hard_stop_leaves_orphans_for_recovery', all(self.alive(i) for i in identities))
        self.start_server(faults=True)
        self.verify('hard_stop_marks_interrupted', self.wait(interrupted)['state'] == 'interrupted')
        self.verify('recovery_stops_worker_and_child', self.children_stopped(identities))
        self.verify('interrupted_not_retried', self.request('/tasks', long_task, key='host-crash')['id'] == interrupted)
        self.verify('interrupted_has_no_new_result', not (self.data / interrupted / 'result.json').exists())
        self.verify('queued_task_recovers', self.wait(queued)['state'] == 'succeeded')
        self.verify('queued_idempotency_survives', self.request('/tasks', body, key='host-queued')['id'] == queued)
        graceful = self.request('/tasks', long_task)['id']
        identities = self.capture_workers(graceful)
        self.stop_server()
        self.verify('graceful_shutdown_stops_children', self.children_stopped(identities))
        self.start_server(faults=True)
        self.verify('graceful_shutdown_persists_cancelled', self.request(f'/tasks/{graceful}')['state'] == 'cancelled')
        self.verify('queued_task_has_no_reexecution', self.request(f'/tasks/{queued}')['state'] == 'succeeded')
        self.verify('queued_events_not_repeated', self.request(f'/tasks/{queued}/events', raw=True).count('event: state') == 3)
        self.report['status'] = 'passed'

    def finish(self):
        try:
            self.stop_server()
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            self.report.update(status='failed', cleanup_error=str(exc))
            if self.process is not None and self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
        for identity in self.workers:
            if self.alive(identity):
                try:
                    psutil.Process(identity['pid']).kill()
                except psutil.NoSuchProcess:
                    pass
        self.report['cleanup_stopped_tracked_workers'] = self.children_stopped(self.workers)
        if not self.report['cleanup_stopped_tracked_workers']:
            self.report['status'] = 'failed'
        for stream in self.streams:
            stream.close()
        (self.output / 'acceptance.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.tmp/local-http-acceptance' / uuid.uuid4().hex[:10])
    args = parser.parse_args()
    acceptance = LocalAcceptance(args.output)
    try:
        acceptance.run()
    except (OSError, RuntimeError, psutil.Error, subprocess.TimeoutExpired) as exc:
        acceptance.report.update(status='failed', error=str(exc))
    finally:
        acceptance.finish()
    print(acceptance.output / 'acceptance.json')
    print(acceptance.report['status'])
    if acceptance.report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
