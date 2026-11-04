"""Three fixed development tasks test candidate checkpoints against saved v1 failures."""
import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from itertools import pairwise
from pathlib import Path

from evals import local50, repository_checkpoint
from evals.swebench_batch import environment, save
from evals.swebench_mini import ROOT, sha, write

TASKS = ('click-usage-empty', 'toolz-join-unmatched', 'boltons-repeat-equality')
BASELINE = ROOT / '.tmp/local50-chain-20261103'


def audit():
    result = {'baseline_report_sha256': sha(BASELINE / 'report.json'), 'actions': Counter(),
              'tool_errors': Counter(), 'complete_symbol_seen_tasks': [], 'receipt_collision_tasks': [],
              'scope': 'Observed complete symbols may be unrelated to the actual defect; no oracle lookup'}
    for folder in sorted((BASELINE / 'tasks').iterdir()):
        rows = local50.read(folder / 'agent/actions.json')
        result['actions'].update(row.get('action', 'invalid') for row in rows)
        result['tool_errors'].update(row['error']['code'] for row in rows if row.get('status') == 'tool_error')
        if any(row.get('result', {}).get('complete_symbol') for row in rows):
            result['complete_symbol_seen_tasks'].append(folder.name)
        collisions = []
        for first, second in pairwise(rows):
            receipt = first.get('result', {})
            args = second.get('arguments', {})
            if (receipt.get('complete_symbol') and second.get('action') == 'read_file'
                    and args.get('path') == receipt['path'] and args.get('offset', 0) == receipt.get('offset', 0)):
                collisions.append([first['step'], second['step']])
        if collisions:
            result['receipt_collision_tasks'].append({'task': folder.name, 'step_pairs': collisions})
    return result


def worker(path):
    write(path.parent / 'policy.json', {'name': 'repository-checkpoint-v1', 'max_extra_symbol_reads': 2,
                                      'source_sha256': sha(Path(repository_checkpoint.__file__)),
                                      'hidden_feedback': False, 'finish_after_first_valid_candidate': True})
    original_tools, original_explore = local50.RepositoryTools, local50.explore
    try:
        local50.RepositoryTools = repository_checkpoint.LedgerTools
        local50.explore = repository_checkpoint.explore
        local50.worker(path)
    finally:
        local50.RepositoryTools, local50.explore = original_tools, original_explore
    report = local50.read(path.parent / 'agent/report.json')
    report.update(protocol='repository-checkpoint-v1', policy_sha256=sha(path.parent / 'policy.json'))
    write(path.parent / 'agent/report.json', report)


def publish(output, report):
    import httpx
    from langfuse import Langfuse

    from deploy.langfuse.swebench_agent import inference_receipt
    from repairflow.telemetry import configuration

    settings = configuration()
    if settings is None:
        raise ValueError('Require existing local Langfuse')
    client = Langfuse(**settings, timeout=10, flush_at=1, environment='checkpoint-development-pilot')
    receipt = {'status': 'incomplete', 'publication_model_calls': 0, 'inference_receipts': []}
    try:
        for key, row in report['tasks'].items():
            agent = local50.read(output / 'tasks' / key / 'agent/report.json')
            trace_id = agent['observability']['trace_id']
            client.create_score(trace_id=trace_id, name='local_target_controls_passed',
                                value=int(row['resolved']), data_type='NUMERIC')
        client.flush()
        with httpx.Client(base_url=settings['base_url'], auth=(settings['public_key'], settings['secret_key']),
                          timeout=10, trust_env=False) as reader:
            for key in report['tasks']:
                agent = local50.read(output / 'tasks' / key / 'agent/report.json')
                trace_id = agent['observability']['trace_id']
                response = reader.get('/api/public/v2/observations', params={
                    'traceId': trace_id, 'limit': 1000, 'fields': 'basic,usage'})
                response.raise_for_status()
                item = inference_receipt(response.json()['data'], {**agent, 'inference_trace_id': trace_id})
                if item is None:
                    raise ValueError('Inference usage receipt mismatch: ' + key)
                receipt['inference_receipts'].append(item)
        receipt['status'] = 'passed'
        return receipt
    finally:
        write(output / 'langfuse.json', receipt)
        client.shutdown()


def run(output):
    import urllib.request

    from sandbox import runner

    baseline_protocol = local50.read(BASELINE / 'protocol.json')
    if any(sha(ROOT / name) != value for name, value in baseline_protocol['source_files'].items()):
        raise ValueError('Keep the baseline implementation unchanged')
    identity = local50.read(BASELINE / 'identity.json')
    policy = runner.preflight()
    model = json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=10))
    current = next(row['digest'] for row in model['models'] if row['name'] == identity['model'])
    if current != identity['digest'] or policy != identity['sandbox']:
        raise ValueError('Require the baseline model and grading image')
    os.environ['CORECODER_TEST_BACKEND'] = 'docker'
    runner.ACTIVE_POLICY.set(policy)
    output.mkdir(parents=True, exist_ok=False)
    write(output / 'audit.json', audit())
    write(output / 'protocol.json', {'policy': 'repository-checkpoint-v1', 'tasks': TASKS, 'identity': identity,
        'selection': 'Three previously inspected development failures; no heldout claim',
        'unchanged_config': baseline_protocol, 'baseline_report_sha256': sha(BASELINE / 'report.json'),
        'policy_source_sha256': sha(Path(repository_checkpoint.__file__)), 'pilot_source_sha256': sha(Path(__file__)),
        'changes': ['Receipt identity includes kind and symbol', 'Explicit generation phase after a complete symbol read',
                    'Candidate requests retain complete symbols instead of overlapping file prefixes'],
        'not_a_component_ablation': True, 'hidden_grading_feedback': False, 'model_attempts_per_task': 1})
    for module in (repository_checkpoint, sys.modules[__name__]):
        source = Path(module.__file__)
        target = output / 'implementation' / source.name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(source.read_bytes())
    cases = {case['task_id']: case for case in local50.read(local50.MANIFEST)['cases']}
    baseline = local50.read(BASELINE / 'report.json')
    report = {'status': 'running', 'tasks': {}, 'baseline': {key: baseline['tasks'][key] for key in TASKS}}
    write(output / 'report.json', report)
    for key in TASKS:
        case, folder = cases[key], output / 'tasks' / key
        folder.mkdir(parents=True)
        # Public input and seed only; no reference repair, grading labels or file hints.
        public = local50.read(BASELINE / 'tasks' / key / 'public.json')
        write(folder / 'public.json', public)
        write(folder / 'job.json', {'source': case['before'], 'source_hash': case['before_hash'],
                                   'public_sha256': sha(folder / 'public.json')})
        control = local50.read(BASELINE / 'tasks' / key / 'control-reference/summary.json')
        if not all(row['passed'] for row in control.values()) or not baseline['tasks'][key]['controls_passed']:
            raise ValueError('Baseline control admission unavailable')
        with (folder / 'worker.log').open('wb') as stream:
            process = subprocess.run([sys.executable, '-B', '-m', 'evals.checkpoint_pilot', '--worker', folder / 'job.json'],
                cwd=ROOT, env=environment('agent', output), stdout=stream, stderr=subprocess.STDOUT,
                timeout=1350, check=False)
        if process.returncode:
            raise RuntimeError('Worker failed; no automatic inference retry: ' + key)
        agent = local50.read(folder / 'agent/report.json')
        grade = local50.grade(case, folder)
        values = [agent['metrics'].get(name) for name in ('prompt_tokens', 'completion_tokens')]
        report['tasks'][key] = {'resolved': grade['resolved'], 'agent_status': agent['status'],
            'changed_files': agent['changed_files'], 'fresh_model_calls': agent['fresh_model_calls'],
            'total_tokens': sum(values) if all(value is not None for value in values) else None,
            'trace_id': agent['observability'].get('trace_id'), 'grade': grade}
        save(output / 'report.json', report)
        print(key, agent['status'], 'resolved=', grade['resolved'], flush=True)
    report.update(status='completed', summary={
        'tasks': 3, 'baseline_resolved': sum(report['baseline'][key]['resolved'] for key in TASKS),
        'candidate_resolved': sum(row['resolved'] for row in report['tasks'].values()),
        'baseline_nonempty_patches': sum(report['baseline'][key]['nonempty_patch'] for key in TASKS),
        'candidate_nonempty_patches': sum(bool(row['changed_files']) for row in report['tasks'].values()),
        'baseline_tokens': sum(report['baseline'][key]['total_tokens'] for key in TASKS),
        'candidate_tokens': sum(row['total_tokens'] or 0 for row in report['tasks'].values()),
        'candidate_fresh_calls': sum(row['fresh_model_calls'] for row in report['tasks'].values())})
    save(output / 'report.json', report)
    report['observability'] = publish(output, report)['status']
    save(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path)
    group.add_argument('--worker', type=Path)
    args = parser.parse_args()
    path = (args.worker or args.output).resolve()
    if not path.is_relative_to(ROOT / '.tmp') or (os.name == 'nt' and path.drive.lower() != 'd:'):
        parser.error('Use project .tmp on D:')
    if args.worker:
        worker(path)
    else:
        print(json.dumps(run(path)['summary']))


if __name__ == '__main__':
    main()
