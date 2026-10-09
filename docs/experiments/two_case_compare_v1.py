"""One correction per arm: failed-operation context with/without public runtime facts."""
import argparse
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

from docs.experiments import failure_operation_compare_v1 as operations
from docs.experiments import two_case_runtime_v1 as runtime
from evals.process import run_process
from evals.runner import digest, snapshot
from evals.runtime import Events

baseline, guarded, previous = operations.baseline, operations.guarded, operations.previous
TASKS = ('more-range-membership', 'click-prompt-suffix')
POLICIES = ('operations', 'runtime')


def worker(path):
    job = baseline.load(path)
    root = path.parent
    provider = llm = None
    events = Events(root / 'trace.jsonl', job['policy'])
    result = {'status': 'agent_error', 'published': False}
    try:
        config = previous.repair.config()
        previous.repair.check_identity(config)
        provider = previous.Provider('qwen', events)
        llm = previous.CheckedBudgetLLM(operations.replay.SharedFirstProvider(provider, Path(job['shared_first'])), config, events)

        def refresh(workspace, allowed, seeds):
            payload = operations.shared_payload(Path(job['shared_first']))
            packed = operations.selection.select(workspace, allowed, seeds, payload['test_code'], payload['observations'])
            previous.write_json(root / 'operation-selection.json', packed)
            return packed

        def feedback(outcomes, workspace, current_job, current_root):
            payload = operations.replay.shared_feedback(outcomes, workspace, current_job, current_root)
            if job['policy'] == 'runtime':
                observation = runtime.observe(workspace, current_job, root / 'runtime-probe', outcomes)
                if observation is not None:
                    payload['public_runtime_observations'] = observation
                events.emit('two_case_runtime_observation', added=observation is not None)
            return payload

        if job['policy'] not in POLICIES:
            raise ValueError('Unknown policy')
        with patch.object(guarded, 'feedback', feedback), patch.object(previous, 'refresh_seeds', refresh):
            result = guarded.run_candidate(llm, job, events)
        if digest(snapshot(root / 'initial-workspace')) != job['shared_candidate_hash']:
            raise ValueError('Shared candidate changed')
        previous.repair.check_identity(config)
    except Exception as exc:  # noqa: BLE001 - retain and score failed attempts
        result.update(status='agent_error', error_type=type(exc).__name__, published=False)
        if (root / 'original-workspace').exists():
            guarded.restore(Path(job['workspace']), root / 'original-workspace', root)
    finally:
        calls = provider.calls if provider else []
        fresh = [c for c in calls if not c.get('replayed')]
        result.update(metrics=llm.metrics() if llm else None, provider_calls=calls,
                      new_model_calls=len(fresh), new_model_tokens=sum(c.get('total_tokens') or 0 for c in fresh))
        previous.write_json(root / 'worker-result.json', events.clean(result))
        if provider:
            provider.client.close()


def summary(rows):
    return {p: {'tasks': len(rr := [r for r in rows if r['policy'] == p]),
                'passed': sum(r['accepted'] for r in rr),
                'new_calls': sum(r['worker'].get('new_model_calls', 0) for r in rr),
                'new_tokens': sum(r['worker'].get('new_model_tokens', 0) for r in rr),
                'budget_tokens_including_replay': sum((r['worker'].get('metrics') or {}).get('budget_accounted_tokens', 0)
                                                     for r in rr)} for p in POLICIES}


def run(output):
    source = baseline.BASE / 'system-comparison-v1-rerun'
    manifest = baseline.load(source / 'manifest.json')
    baseline.intact(manifest)
    if not baseline.load(source / 'experiment.json')['complete']:
        raise ValueError('Completed baseline required')
    cases = [next(c for c in manifest['cases'] if c['task_id'] == task) for task in TASKS]
    protected = [source.resolve()] + [Path(c[k]).resolve() for c in manifest['cases']
                                      for k in ('before', 'after', 'checks', 'harness', 'frozen_harness')]
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('Fresh nonoverlapping output required')
    if any(c['split'] != 'development' for c in cases):
        raise ValueError('Development only')
    output.mkdir(parents=True)
    paths = [source / 'manifest.json', source / 'experiment.json', Path(__file__), Path(runtime.__file__), runtime.PROBE,
             Path(operations.__file__), Path(operations.selection.__file__), Path(operations.replay.__file__)]
    shared_hashes = {}
    for c in cases:
        shared = source / 'runs' / c['task_id'] / 'full'
        if baseline.load(shared / 'worker-result.json')['initial']['status'] != 'completed':
            raise ValueError('Completed shared first required')
        paths += [shared / name for name in ('initial-messages.json', 'initial-response.txt', 'feedback-messages.json', 'worker-result.json')]
        shared_hashes[c['task_id']] = digest(snapshot(shared / 'initial-workspace'))
    hashes = {str(p.resolve()): previous.admission.history.sha(p) for p in paths}
    report = {'complete': False, 'runs': [], 'protocol': {'name': 'two-case-runtime-v1', 'tasks': TASKS,
              'policies': POLICIES, 'input_hashes': hashes, 'config': previous.repair.config().to_dict(),
              'shared_candidate_hashes': shared_hashes, 'change': 'Only append bounded real public runtime observations in round two',
              'unchanged': 'Shared historical first candidate charged to budget; operation fragments, public text, model and system prompt identical',
              'limits': 'Two known development failures; hand-authored diagnostic families; no manual patch/results enter jobs or prompts',
              'caps': '2 calls including replay, 15000 tokens, 2048 output, 5 source spans/6000 chars; runtime payload <=4000 chars, 15s',
              'default_changed': False}}

    def intact():
        baseline.intact(manifest)
        if any(previous.admission.history.sha(Path(p)) != value for p, value in hashes.items()):
            raise ValueError('Frozen input changed')
        for c in cases:
            if digest(snapshot(source / 'runs' / c['task_id'] / 'full/initial-workspace')) != shared_hashes[c['task_id']]:
                raise ValueError('Shared candidate changed')

    def save():
        report['summary'] = summary(report['runs'])
        previous.write_json(output / 'experiment.json', report)

    previous.repair.check_identity(previous.repair.config())
    save()
    for number, case in enumerate(cases):
        for policy in POLICIES[::1 if number % 2 == 0 else -1]:
            intact()
            root = output / case['task_id'] / policy
            workspace = root / 'workspace'
            shutil.copytree(case['before'], workspace)
            shared = source / 'runs' / case['task_id'] / 'full'
            job = {k: case[k] for k in ('description', 'allowed_files', 'package', 'source_root', 'evidence',
                                      'description_hash', 'harness', 'harness_hash', 'frozen_harness', 'frozen_harness_hash')}
            job.update(workspace=str(workspace), original_hash=case['before_hash'], policy=policy,
                       shared_first=str(shared), shared_candidate_hash=shared_hashes[case['task_id']])
            previous.write_json(root / 'job.json', job)
            process = run_process([sys.executable, '-B', '-m', 'docs.experiments.two_case_compare_v1', '--worker', str(root / 'job.json')],
                                  baseline.ROOT, 600, root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                                  dict(os.environ, PYTHONPATH=str(baseline.ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
            path = root / 'worker-result.json'
            result = baseline.load(path) if path.exists() and not process['timed_out'] else {'status': 'worker_failed'}
            intact()
            grade = root / 'verification'
            grade.mkdir()
            verified = previous.baseline.verify(case, workspace, grade)
            public = previous.public_check(workspace, case['harness'], case['package'], case['source_root'], root / 'final-public')
            frozen = previous.public_check(workspace, case['frozen_harness'], case['package'], case['source_root'], root / 'final-frozen')
            accepted = result['status'] == 'completed' and verified['passed'] and previous.all_pass(public) and previous.all_pass(frozen)
            report['runs'].append({'task_id': case['task_id'], 'policy': policy, 'accepted': accepted,
                                   'worker': result, 'verification': verified, 'public': public, 'frozen': frozen, 'process': process})
            save()
            print(case['task_id'], policy, result['status'], 'accepted=', accepted, flush=True)
    intact()
    previous.repair.check_identity(previous.repair.config())
    report['complete'] = len(report['runs']) == len(TASKS) * len(POLICIES)
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker.resolve())
    elif args.output:
        run(args.output.resolve())
    else:
        parser.error('Require --output or --worker')
