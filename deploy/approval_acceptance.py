"""Real HTTP approval/restart/crash acceptance with private port and task data."""

import argparse
import subprocess
import uuid
from pathlib import Path

import psutil

from deploy.acceptance import ROOT
from deploy.local_acceptance import LocalAcceptance


class ApprovalAcceptance(LocalAcceptance):
    def run(self):
        self.report['kind'] = 'approval-host-http'
        self.start_server()
        body = {'task_id': 'timeout-units', 'mode': 'scripted', 'workflow': 'langgraph-approval-v1'}
        task_id = self.request('/tasks', body, key='approval-http')['id']
        waiting = self.wait(task_id, {'awaiting_approval'})
        snapshot = self.request(f'/tasks/{task_id}/artifacts/workflow.json')
        self.verify('waiting_does_not_execute', not (self.data / task_id / 'runs').exists())
        self.verify('plan_is_visible', snapshot['plan']['task_id'] == body['task_id'])
        self.verify('native_checkpoint_exists', (self.data / task_id / 'checkpoints.sqlite3').is_file())
        self.stop_server(hard=True)
        self.start_server()
        self.verify('pending_survives_hard_restart', self.request(f'/tasks/{task_id}') == waiting)
        self.verify('pending_snapshot_preserved', self.request(f'/tasks/{task_id}/artifacts/workflow.json') == snapshot)
        self.verify('pending_idempotency_preserved', self.request('/tasks', body, key='approval-http')['id'] == task_id)
        self.request(f'/tasks/{task_id}/approval', {'decision': 'approve'})
        self.request(f'/tasks/{task_id}/approval', {'decision': 'approve'})
        completed = self.wait(task_id)
        self.verify('approved_independent_verification', completed['state'] == 'succeeded'
                    and completed['result']['verification']['passed'])
        self.verify('duplicate_approval_executes_once', len(list((self.data / task_id / 'runs').iterdir())) == 1)
        self.stop_server()
        self.start_server()
        self.verify('completed_approval_survives_restart',
                    self.request(f'/tasks/{task_id}/approval', {'decision': 'approve'}) == completed)
        rejected_id = self.request('/tasks', body)['id']
        self.wait(rejected_id, {'awaiting_approval'})
        self.request(f'/tasks/{rejected_id}/approval', {'decision': 'reject'})
        self.verify('rejected_never_executes', self.wait(rejected_id)['state'] == 'rejected'
                    and not (self.data / rejected_id / 'runs').exists())
        cancelled_id = self.request('/tasks', body)['id']
        self.wait(cancelled_id, {'awaiting_approval'})
        self.request(f'/tasks/{cancelled_id}/cancel', {})
        self.verify('cancelled_pending_never_executes', self.wait(cancelled_id)['state'] == 'cancelled'
                    and not (self.data / cancelled_id / 'runs').exists())
        self.stop_server()
        self.start_server(faults=True)
        crash_body = {**body, 'mode': 'unchanged'}
        interrupted = self.request('/tasks', crash_body, key='approval-crash')['id']
        self.wait(interrupted, {'awaiting_approval'})
        self.request(f'/tasks/{interrupted}/approval', {'decision': 'approve'})
        identities = self.capture_workers(interrupted)
        self.verify('execution_claim_exists', (self.data / interrupted / 'execution-started').is_file())
        self.stop_server(hard=True)
        self.verify('crash_leaves_workers_for_recovery', all(self.alive(i) for i in identities))
        self.start_server(faults=True)
        recovered = self.wait(interrupted)
        self.verify('started_execution_marked_interrupted', recovered['state'] == 'interrupted')
        self.verify('recovery_stops_worker_tree', self.children_stopped(identities))
        self.verify('duplicate_approval_does_not_replay_crash',
                    self.request(f'/tasks/{interrupted}/approval', {'decision': 'approve'}) == recovered)
        self.verify('resubmit_does_not_replay_crash',
                    self.request('/tasks', crash_body, key='approval-crash')['id'] == interrupted)
        self.verify('crashed_execution_has_no_result', not (self.data / interrupted / 'result.json').exists())
        self.report['status'] = 'passed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.tmp/approval-http-acceptance' / uuid.uuid4().hex[:10])
    acceptance = ApprovalAcceptance(parser.parse_args().output)
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
