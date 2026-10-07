"""Opt-in approval and certified task execution using the frozen tentative worker."""
import difflib
import hashlib
import json
import shutil
from pathlib import Path

from docs.experiments import tentative_feedback_worker_v1 as worker
from evals.runtime import Events

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = 'tentative-approval-v1'
TASKS = ('click-usage-empty', 'itsdangerous-none-salt')
RECORD = ROOT / '.tmp/real-defects/tentative-publication-compare-v1-certified'
RECORD_SHA256 = 'e76ffde19a06d1e58dc2db90589f8f486da13a3e1c56a105e74ed53bd1cb4da8'
JOB_HASHES = {
    'click-usage-empty': 'dde09f5ef3a662b14f3072d902d6308a72d3161c290cc7b1f1a2362e4dc82dff',
    'itsdangerous-none-salt': '7d5f69fc5566748cdc36f1048b161998cc13484263e0bb22b6ee58889e90e686',
}


def load_task(task_id):
    """Server-owned historical inputs; no caller-supplied paths or private scoring."""
    if task_id not in TASKS:
        raise ValueError('Unknown certified task')
    path = RECORD/'experiment.json'
    if hashlib.sha256(path.read_bytes()).hexdigest() != RECORD_SHA256:
        raise ValueError('Certified experiment changed')
    report = json.loads(path.read_text(encoding='utf-8'))
    if not report['complete']:
        raise ValueError('Incomplete certification')
    for name, expected in report['protocol']['adapter_hashes'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen implementation or certification changed')
    job_path = RECORD/task_id/'tentative-publication/job.json'
    if hashlib.sha256(job_path.read_bytes()).hexdigest() != JOB_HASHES[task_id]:
        raise ValueError('Certified job template changed')
    task = json.loads(job_path.read_text(encoding='utf-8'))
    admission = 'validation-admission-v1-final' if task_id == TASKS[0] else 'second-repo-admission-v1-final'
    source = ROOT/'.tmp/real-defects'/admission/task_id/'before'
    if worker.repair.digest(worker.repair.snapshot(source)) != report['protocol']['source_hashes'][task_id]:
        raise ValueError('Certified task source changed')
    worker.repair.validate_evidence(source, task['allowed_files'], task['evidence'])
    if task['task_id'] != task_id or task['check_code_hash'] != report['protocol']['public_check_versions'][task_id]:
        raise ValueError('Certified public check identity changed')
    check = worker.gate.PublicCheck(Path(task['harness']), worker.tentative.canonical_check(task_id),
                                  task['check_code_hash'], task['harness_hash'], task_id)
    worker.gate.validate_check(check)
    return source, task


def run(path, decision=None, load=load_task, execute=None):
    """Approval precedes inference; started execution is never automatically replayed."""
    path = Path(path).resolve()
    request = json.loads(path.read_text(encoding='utf-8'))['request']
    if request.get('workflow') != WORKFLOW or request.get('suite') != 'certified' or request.get('mode') != 'live':
        raise ValueError('Certified tentative workflow requires live mode')
    if decision not in {None, 'approve', 'reject'}:
        raise ValueError('Unknown approval decision')
    root = path.parent
    snapshot_path = root/'workflow.json'
    identity = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    if snapshot_path.exists():
        snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
        if snapshot['request_hash'] != identity or snapshot['workflow'] != WORKFLOW:
            raise ValueError('Approval checkpoint belongs to another request')
        if snapshot['stage'] != 'awaiting_approval':
            raise ValueError('Started or terminal tentative execution cannot be replayed')
    else:
        source, task = load(request['task_id'])
        shutil.copytree(source, root/'source')
        snapshot = {'workflow': WORKFLOW, 'request_hash': identity, 'stage': 'awaiting_approval',
                    'task_id': request['task_id'], 'task_start_sha256': worker.gate.digest(worker.gate.structural.files(root/'source')),
                    'plan': {'task_id': request['task_id'], 'allowed_files': task['allowed_files'],
                             'max_llm_calls': 2, 'token_budget': 15000, 'publication': 'certified public checks'},
                    'decision': None}
    def save(stage):
        snapshot['stage'] = stage
        temporary = root/'workflow.tmp'
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(snapshot_path)
    if decision is None:
        save('awaiting_approval')
        return {'status': 'awaiting_approval', 'accepted': False}
    snapshot['decision'] = decision
    if decision == 'reject':
        save('rejected')
        return {'status': 'approval_rejected', 'accepted': False}
    with (root/'execution-started').open('x', encoding='utf-8') as marker:
        marker.write('Do not replay started execution.\n')
    save('executing')
    _, task = load(request['task_id'])
    workspace = root/'source'
    if worker.gate.digest(worker.gate.structural.files(workspace)) != snapshot['task_start_sha256']:
        raise ValueError('Task source changed while awaiting approval')
    before = worker.gate.structural.files(workspace)
    artifact = root/'runs'/'tentative'
    artifact.mkdir(parents=True)
    task = dict(task, workspace=str(workspace))
    if execute is None:
        worker.repair.check_identity(worker.repair.config())
        job = artifact/'job.json'
        job.write_text(json.dumps(task), encoding='utf-8')
        worker.worker(job)
        result = json.loads((artifact/'worker-result.json').read_text(encoding='utf-8'))
    else:
        result = execute(task, Events(artifact/'trace.jsonl', root.name))
    committed = result.get('committed') is True and result.get('status') == 'completed'
    public = (result.get('publication') or {}).get('public_check') or {}
    accepted = committed and public.get('passed') is True
    report = {'status': 'passed' if accepted else result.get('status', 'agent_error'), 'accepted': accepted,
              'verification': {'passed': accepted, 'scope': 'certified public checks only; no private scoring'},
              'metrics': result.get('metrics'), 'publication': result.get('publication'),
              'original_unchanged': result.get('original_unchanged'), 'artifacts': str(artifact)}
    after = worker.gate.structural.files(workspace)
    diff = ''.join(''.join(difflib.unified_diff(before[name].decode('utf-8').splitlines(True),
                                              after[name].decode('utf-8').splitlines(True),
                                              fromfile=f'a/{name}', tofile=f'b/{name}'))
                   for name in sorted(before) if before[name] != after[name])
    (artifact/'patch.diff').write_text(diff, encoding='utf-8')
    report['task_end_sha256'] = worker.gate.digest(after)
    (artifact/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    save('succeeded' if accepted else 'failed')
    return report
