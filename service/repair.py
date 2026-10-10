"""Trusted bundle registry and approval adapter for the shared repair engine."""
import os
import re
from pathlib import Path

from evals.schema import Task
from repairflow.bundles import ROOT, load
from repairflow.engine import config, execute

WORKFLOW = 'repair-approval-v1'


def registry():
    return Path(os.environ.get('CORECODER_REPAIR_BUNDLES', str(ROOT / '.tmp/repair-bundles'))).resolve()


def load_task(task_id):
    if not re.fullmatch('[a-z0-9][a-z0-9_-]{0,79}', task_id):
        raise ValueError('Invalid repair task')
    root = registry() / task_id
    if root.is_symlink() or not root.resolve().is_relative_to(registry()):
        raise ValueError('Linked task directory')
    data = load(root)
    if data['task_id'] != task_id:
        raise ValueError('Bundle task identity mismatch')
    return root, data


def catalog():
    rows = []
    for path in sorted(registry().glob('*/bundle.json')):
        try:
            _, data = load_task(path.parent.name)
        except (OSError, ValueError, KeyError):
            continue
        rows.append({'task_id': data['task_id'], 'title': data['description'], 'workflow': WORKFLOW,
                     'modes': ['live', 'replay'] if 'replay_sha256' in data else ['live']})
    return rows


def run(path, decision=None):
    from repairflow.bundles import read
    from workflows.approval import run_approval_workflow

    path = Path(path).resolve()
    request = read(path)['request']
    if (request.get('workflow') != WORKFLOW or request.get('suite') != 'repair'
            or request.get('mode') not in {'live', 'replay'} or request.get('search_backend') != 'off'):
        raise ValueError('Invalid shared repair workflow request')
    root, data = load_task(request['task_id'])
    task = Task(data['task_id'], data['task_id'], data['description'], tuple(data['allowed_files']), root)
    # Pin all task metadata as well as source/check hashes across approval/restart.
    pin = path.parent / 'bundle-pin.txt'
    if pin.exists() and pin.read_text(encoding='utf-8') != data['bundle_hash']:
        raise ValueError('Approved bundle metadata changed')
    if not pin.exists():
        with pin.open('x', encoding='utf-8') as stream:
            stream.write(data['bundle_hash'])

    def perform(_task, _settings, output):
        return execute(root, request['mode'], output)

    return run_approval_workflow(task, config(request['mode']), path.parent, decision=decision, execute=perform)
