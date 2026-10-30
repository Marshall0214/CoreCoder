"""One offline CLI/API demonstration of an administrator-owned scripted Issue."""
import os
import time
from pathlib import Path

from repairflow.bundles import read, write
from repairflow.issue_registry import load
from repairflow.issue_repair import execute


def run(entry, output):
    from fastapi.testclient import TestClient

    from service.app import create_app

    entry, output = Path(entry).absolute(), Path(output).resolve()
    metadata, _ = load(entry)
    if not metadata['scripted_responses']:
        raise ValueError('Offline demo requires administrator-owned scripted responses')
    if output.exists() or output.is_relative_to(entry.resolve()) or entry.resolve().is_relative_to(output):
        raise ValueError('Demo output must be new and outside the Issue entry')
    output.mkdir(parents=True)
    evidence = output / 'evidence'
    evidence.mkdir()
    original_registry = os.environ.get('CORECODER_ISSUE_TASKS')
    os.environ['CORECODER_ISSUE_TASKS'] = str(entry.parent)

    def wait(client, task_id, target=None):
        from service.manager import TERMINAL

        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            response = client.get('/tasks/' + task_id)
            response.raise_for_status()
            state = response.json()
            if state['state'] == target or target is None and state['state'] in TERMINAL:
                return state
            if target is not None and state['state'] in TERMINAL:
                raise ValueError('Task finished before reaching the expected approval state')
            time.sleep(0.05)
        raise TimeoutError('Demo task did not reach its expected state')

    def submit(client, key):
        response = client.post('/tasks', headers={'Idempotency-Key': key}, json={
            'suite': 'issues', 'task_id': metadata['task_id'], 'mode': 'scripted', 'workflow': 'issue-approval-v1'})
        response.raise_for_status()
        return response.json()['id']

    try:
        cli = execute(entry / 'prepared', entry / 'config/task.json', output / 'cli', mode='scripted',
                      responses=entry / 'responses.json', model=metadata['model'], workflow='symbol-recovery-v1',
                      observation_policy=metadata['observation_policy'])
        with TestClient(create_app(output / 'api', timeout=1200)) as client:
            task_id = submit(client, 'offline-issue-demo')
            if submit(client, 'offline-issue-demo') != task_id:
                raise ValueError('Idempotent submission created a duplicate task')
            wait(client, task_id, 'awaiting_approval')
            if (output / 'api' / task_id / 'runs').exists():
                raise ValueError('Repair executed before approval')
        with TestClient(create_app(output / 'api', timeout=1200)) as client:
            if client.get('/tasks/' + task_id).json()['state'] != 'awaiting_approval':
                raise ValueError('Approval was not restored across restart')
            client.post('/tasks/' + task_id + '/approval', json={'decision': 'approve'}).raise_for_status()
            state = wait(client, task_id)
            for name in ('report.json', 'patch.diff', 'actions.json', 'trace.jsonl', 'provenance.json', 'observability.json'):
                response = client.get('/tasks/' + task_id + '/artifacts/' + name)
                response.raise_for_status()
                (evidence / name).write_bytes(response.content)
            report = read(evidence / 'report.json')
            if (output / 'cli/patch.diff').read_bytes() != (evidence / 'patch.diff').read_bytes():
                raise ValueError('CLI and API patches differ')
            expected_state = 'ready_for_review' if cli['public_checks_passed'] else 'failed'
            if state['state'] != expected_state or report['status'] != cli['status']:
                raise ValueError('CLI and API repair outcomes differ')
            if cli['fresh_model_calls'] or report['fresh_model_calls'] or report['accepted']:
                raise ValueError('Offline demo called a model or claimed independent acceptance')
            (evidence / 'events.sse').write_text(client.get('/tasks/' + task_id + '/events').text, encoding='utf-8')
            before = (evidence / 'report.json').read_bytes()
            client.post('/tasks/' + task_id + '/approval', json={'decision': 'approve'}).raise_for_status()
            if client.get('/tasks/' + task_id + '/artifacts/report.json').content != before:
                raise ValueError('Repeated approval executed the task again')
            rejected = submit(client, 'offline-issue-reject')
            wait(client, rejected, 'awaiting_approval')
            client.post('/tasks/' + rejected + '/approval', json={'decision': 'reject'}).raise_for_status()
            if wait(client, rejected)['state'] != 'rejected' or (output / 'api' / rejected / 'runs').exists():
                raise ValueError('Rejected task executed')
        acceptance = {'status': 'passed', 'scope': 'Offline scripted engineering demonstration, not model repair accuracy',
                      'fresh_model_calls': 0, 'independent_acceptance': False, 'repair_status': cli['status'],
                      'api_state': state['state'], 'same_patch': True, 'approval_restart': True,
                      'idempotent_submission': True, 'repeated_approval_no_execution': True,
                      'rejection_no_execution': True, 'task_id': task_id, 'rejected_task_id': rejected}
        write(output / 'acceptance.json', acceptance)
        return acceptance
    finally:
        if original_registry is None:
            os.environ.pop('CORECODER_ISSUE_TASKS', None)
        else:
            os.environ['CORECODER_ISSUE_TASKS'] = original_registry
