"""Offline acceptance through the real CLI engine, ASGI app and worker processes."""
import os
import time
from pathlib import Path

from repairflow.bundles import load, write
from repairflow.engine import execute


def run(bundle, output):
    from fastapi.testclient import TestClient

    from service.app import create_app

    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    data = load(bundle)
    if output.exists() or bundle.name != data['task_id']:
        raise ValueError('Use a new demo output and a bundle directory named after its task')
    cli = execute(bundle, 'replay', output / 'cli')
    if not cli['accepted']:
        raise ValueError('Replay failed; see CLI artifacts')
    previous = os.environ.get('CORECODER_REPAIR_BUNDLES')
    os.environ['CORECODER_REPAIR_BUNDLES'] = str(bundle.parent)
    request = {'suite': 'repair', 'task_id': data['task_id'], 'mode': 'replay', 'workflow': 'repair-approval-v1'}

    def wait(client, task_id, terminal=False):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            response = client.get('/tasks/' + task_id)
            response.raise_for_status()
            row = response.json()
            if row['state'] in ({'succeeded', 'failed', 'rejected', 'cancelled', 'timed_out'} if terminal else {'awaiting_approval'}):
                return row
            time.sleep(0.05)
        raise TimeoutError('Demo task did not reach expected state')

    try:
        with TestClient(create_app(output / 'api', timeout=1200)) as client:
            response = client.post('/tasks', json=request, headers={'Idempotency-Key': 'shared-repair-demo'})
            response.raise_for_status()
            task_id = response.json()['id']
            duplicate = client.post('/tasks', json=request, headers={'Idempotency-Key': 'shared-repair-demo'})
            duplicate.raise_for_status()
            assert duplicate.json()['id'] == task_id
            wait(client, task_id)
            assert not (output / 'api' / task_id / 'runs').exists()
        # A new manager and native LangGraph checkpoint restore the same pending approval.
        with TestClient(create_app(output / 'api', timeout=1200)) as client:
            assert client.get('/tasks/' + task_id).json()['state'] == 'awaiting_approval'
            client.post(f'/tasks/{task_id}/approval', json={'decision': 'approve'}).raise_for_status()
            row = wait(client, task_id, terminal=True)
            assert row['state'] == 'succeeded', row
            evidence = output / 'evidence'
            evidence.mkdir()
            for name in ('workflow.json', 'patch.diff', 'report.json', 'context-selection.json', 'trace.jsonl', 'provenance.json'):
                artifact = client.get(f'/tasks/{task_id}/artifacts/{name}')
                artifact.raise_for_status()
                (evidence / name).write_bytes(artifact.content)
            events = client.get(f'/tasks/{task_id}/events')
            events.raise_for_status()
            (evidence / 'events.sse').write_text(events.text, encoding='utf-8')
            assert 'awaiting_approval' in events.text and 'succeeded' in events.text
            assert (evidence / 'patch.diff').read_bytes() == (output / 'cli/patch.diff').read_bytes()
            rejected = client.post('/tasks', json=request)
            rejected.raise_for_status()
            rejected_id = rejected.json()['id']
            wait(client, rejected_id)
            client.post(f'/tasks/{rejected_id}/approval', json={'decision': 'reject'}).raise_for_status()
            assert wait(client, rejected_id, terminal=True)['state'] == 'rejected'
            assert not (output / 'api' / rejected_id / 'runs').exists()
        result = {'passed': True, 'mode': 'historical single-call replay; not fresh model evaluation',
                  'fresh_model_calls': 0, 'bundle_hash': data['bundle_hash'], 'task_id': data['task_id'],
                  'service_task_id': task_id, 'cli_and_api_patch_identical': True,
                  'checks': ['retrieval', 'constrained patch', 'public checks', 'independent Target/Controls',
                             'idempotency', 'approval restart', 'real service worker', 'SSE', 'artifact downloads',
                             'approval rejection without execution'],
                  'transport': 'in-process ASGI HTTP client; worker executes in a real child process'}
        write(output / 'acceptance.json', result)
        return result
    finally:
        if previous is None:
            os.environ.pop('CORECODER_REPAIR_BUNDLES', None)
        else:
            os.environ['CORECODER_REPAIR_BUNDLES'] = previous
