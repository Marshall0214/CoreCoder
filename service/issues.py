"""Issue task catalog and durable approval adapter for the CLI repair engine."""
import os
from pathlib import Path

from evals.schema import RunConfig, Task
from repairflow.bundles import ROOT, read
from repairflow.issue_execution import FEEDBACK, LEGACY, ApprovalConfig, limits
from repairflow.issue_registry import identity, load
from repairflow.issue_repair import execute
from sandbox import runner

WORKFLOW = 'issue-approval-v1'


def registry():
    return Path(os.environ.get('CORECODER_ISSUE_TASKS', str(ROOT / '.tmp/issue-tasks'))).absolute()


def load_task(task_id):
    root = registry() / identity(task_id)
    if not root.resolve().is_relative_to(registry().resolve()):
        raise ValueError('Issue task is outside the trusted registry')
    entry, task = load(root)
    return root, entry, task


def catalog():
    rows = []
    for path in sorted(registry().glob('*/entry.json')):
        try:
            _, entry, task = load_task(path.parent.name)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        rows.append({'task_id': entry['task_id'], 'title': task['description'].split('\n', 1)[0],
                     'workflow': WORKFLOW, 'modes': ['scripted', 'live'] if entry['scripted_responses'] else ['live'],
                     'model': entry['model'], 'thinking': False, 'requires_review': True,
                     'independent_verification': False})
        if entry.get('engine') == FEEDBACK:
            rows[-1].update(engine=FEEDBACK, execution_profile=entry['execution_profile'])
    return rows


def run(path, decision=None):
    from workflows.approval import run_approval_workflow

    path = Path(path).resolve()
    request = read(path)['request']
    if (request.get('suite') != 'issues' or request.get('workflow') != WORKFLOW
            or request.get('mode') not in {'scripted', 'live'} or request.get('search_backend') != 'off'):
        raise ValueError('Invalid Issue workflow request')
    root, entry, data = load_task(request['task_id'])
    if request['mode'] == 'scripted' and not entry['scripted_responses']:
        raise ValueError('No administrator-owned scripted responses')
    # Pin metadata plus every input, model and scope across approval and service restart.
    pin = path.parent / 'issue-pin.txt'
    if pin.exists() and pin.read_text(encoding='utf-8') != entry['entry_sha256']:
        raise ValueError('Approved Issue entry changed')
    if not pin.exists():
        with pin.open('x', encoding='utf-8') as stream:
            stream.write(entry['entry_sha256'])
    task = Task(entry['task_id'], entry['task_id'], data['description'], tuple(data['allowed_files']), root)
    selected_engine = entry.get('engine', LEGACY)
    effective = None
    if selected_engine == FEEDBACK:
        service_cap = os.environ.get('CORECODER_SERVICE_TIMEOUT_SECONDS')
        effective = limits(entry['execution_profile'], float(service_cap) if service_cap else None)
        settings = ApprovalConfig(mode=request['mode'], model=entry['model'],
                                  max_rounds=effective['exploration_requests'] + effective['feedback_requests'],
                                  wall_timeout=effective['total_seconds'])
    else:
        settings = RunConfig(mode='scripted' if request['mode'] == 'scripted' else 'live', model=entry['model'],
                             base_url='http://127.0.0.1:11434', reasoning_effort='none', max_rounds=20,
                             token_budget=60000, max_output_tokens=4096, context_tokens=65536, wall_timeout=1200,
                             output_policy='remaining')

    def perform(_task, _settings, output):
        if selected_engine == FEEDBACK:
            report = execute(root / 'prepared', root / 'config/task.json', output,
                             mode='scripted' if request['mode'] == 'scripted' else 'ollama',
                             responses=root / 'responses.json' if request['mode'] == 'scripted' else None,
                             model=entry['model'], workflow=FEEDBACK, execution_profile=entry['execution_profile'],
                             sandbox_owner_path=path.parent, service_timeout_seconds=effective['service_timeout_seconds'])
            return dict(report, artifacts=str(output))
        report = execute(root / 'prepared', root / 'config/task.json', output,
                         mode='scripted' if request['mode'] == 'scripted' else 'ollama',
                         responses=root / 'responses.json' if request['mode'] == 'scripted' else None,
                         model=entry['model'], workflow='symbol-recovery-v1', observation_policy=entry['observation_policy'],
                         sandbox_owner=runner.owner(path.parent))
        return dict(report, artifacts=str(output))

    details = {'read_only_files': data.get('read_only_files', []), 'model': entry['model'],
               'thinking': False, 'observation_policy': entry['observation_policy'],
               'independent_verification': False, 'max_steps': 20, 'max_edit_attempts': 6}
    if effective is not None:
        details.update(engine=selected_engine, execution_profile=entry['execution_profile'], effective_limits=effective,
                       max_steps=effective['exploration_requests'], max_feedback_requests=effective['feedback_requests'])
    return run_approval_workflow(task, settings, path.parent, decision=decision, execute=perform, review_only=True,
                                plan_details=details)
