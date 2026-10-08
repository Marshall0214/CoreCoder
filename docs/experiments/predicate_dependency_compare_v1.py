"""Three repeated pairs: current context vs manually audited predicate dependencies."""
import argparse
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import frozen_feedback_v1 as guarded
from docs.experiments import predicate_dependency_context_v1 as context
from docs.experiments import system_comparison_v1 as baseline
from evals.process import run_process

previous = guarded.previous
TASKS = ('more-predicate-sentinel',)
POLICIES = ('current', 'dependencies')
REPEATS = 3


def summary(rows):
    return {p: {'tasks': len(rr := [r for r in rows if r['policy'] == p]),
                'passed': sum(r['accepted'] for r in rr),
                'controls_passed': sum(bool((r['verification'].get('groups') or {}).get('Controls', {}).get('passed')) for r in rr),
                'calls': sum((r['worker'].get('metrics') or {}).get('llm_calls', 0) for r in rr),
                'tokens': sum((r['worker'].get('metrics') or {}).get('budget_accounted_tokens', 0) for r in rr),
                'missing_worker_results': sum(r['worker'].get('metrics') is None for r in rr),
                'worker_seconds': round(sum(r['process']['seconds'] for r in rr), 4)} for p in POLICIES}


def run(output):
    source = baseline.BASE / 'system-comparison-v1-rerun'
    manifest = baseline.load(source / 'manifest.json')
    history = baseline.load(source / 'experiment.json')
    baseline.intact(manifest)
    if not history['complete'] or history.get('aborted'):
        raise ValueError('Completed 150-run baseline required')
    cases = [next(c for c in manifest['cases'] if c['task_id'] == task) for task in TASKS]
    if any(c['split'] != 'development' for c in cases):
        raise ValueError('Development tasks only')
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Fresh nonoverlapping output required')
    for case in manifest['cases']:
        for key in ('before', 'after', 'checks', 'harness', 'frozen_harness'):
            p = Path(case[key]).resolve()
            if output.is_relative_to(p) or p.is_relative_to(output):
                raise ValueError('Output overlaps frozen sources or tests')
    output.mkdir(parents=True)
    paths = [source / 'manifest.json', source / 'experiment.json', Path(__file__), Path(guarded.__file__), Path(context.__file__), Path(context.adapters.__file__)]
    hashes = {str(p.resolve()): previous.admission.history.sha(p) for p in paths}
    report = {'complete': False, 'runs': [], 'protocol': {'name': 'dependency-context-v1', 'input_hashes': hashes,
              'tasks': TASKS, 'policies': POLICIES, 'config': previous.repair.config().to_dict(),
              'provider': context.adapters.PROVIDERS['qwen'], 'repeats': REPEATS,
              'selection': 'One persistent known development failure, three deterministic repeated pairs; not three distinct tasks',
              'change': 'Only source evidence selection and current-source refresh; manually audited dependency spans from buggy source, no solution or private tests',
              'unchanged': 'Same description, model, temperature 0, max 2 calls, 15000 tokens, 2048 output, 6000 source chars, 5 spans, 600s, feedback and dual validation',
              'limits': 'Manual task-specific dependency audit, context composition and metadata change together; deterministic repeats are not independent task evidence',
              'order': 'Alternating arm order; fresh independent model requests'}}

    def intact():
        baseline.intact(manifest)
        if any(previous.admission.history.sha(Path(p)) != h for p, h in hashes.items()):
            raise ValueError('Frozen comparison source changed')

    def save():
        report['summary'] = summary(report['runs'])
        previous.write_json(output / 'experiment.json', report)

    previous.repair.check_identity(previous.repair.config())
    save()
    for number, case in enumerate(cases * REPEATS):
        for policy in POLICIES[::1 if number % 2 == 0 else -1]:
            intact()
            root = output / case['task_id'] / f'repeat-{number+1:02d}' / policy
            workspace = root / 'workspace'
            shutil.copytree(case['before'], workspace)
            job = {k: case[k] for k in ('description', 'allowed_files', 'package', 'source_root', 'evidence',
                                      'description_hash', 'harness', 'harness_hash', 'frozen_harness', 'frozen_harness_hash')}
            job.update(workspace=str(workspace), original_hash=case['before_hash'], policy=policy)
            if policy == 'dependencies':
                job['evidence'] = context.dependency_evidence(workspace, job['allowed_files'])
            previous.write_json(root / 'job.json', job)
            process = run_process([sys.executable, '-B', '-m', 'docs.experiments.predicate_dependency_context_v1', '--worker', str(root / 'job.json')],
                                  baseline.ROOT, 600, root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                                  dict(os.environ, PYTHONPATH=str(baseline.ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
            p = root / 'worker-result.json'
            result = baseline.load(p) if p.exists() and not process['timed_out'] else {
                'status': 'timeout' if process['timed_out'] else 'agent_error', 'metrics': None, 'published': False}
            intact()
            grade = root / 'verification'
            grade.mkdir()
            verified = previous.baseline.verify(case, workspace, grade)
            public = previous.public_check(workspace, case['harness'], case['package'], case['source_root'], root / 'final-public')
            frozen = previous.public_check(workspace, case['frozen_harness'], case['package'], case['source_root'], root / 'final-frozen')
            accepted = result['status'] == 'completed' and verified['passed'] and previous.all_pass(public) and previous.all_pass(frozen)
            report['runs'].append({'task_id': case['task_id'], 'repeat': number+1, 'policy': policy, 'accepted': accepted,
                                   'worker': result, 'verification': verified, 'public': public, 'frozen': frozen, 'process': process})
            save()
            print(case['task_id'], policy, result['status'], 'accepted=', accepted, flush=True)
    intact()
    previous.repair.check_identity(previous.repair.config())
    report['complete'] = len(report['runs']) == len(TASKS) * REPEATS * 2
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        context.worker(args.worker.resolve())
    elif args.output:
        run(args.output.resolve())
    else:
        parser.error('Require --output or --worker')
