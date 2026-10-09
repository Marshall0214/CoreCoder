"""Shared-first paired corrections: unchanged seeds vs failed-operation context."""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

from docs.experiments import failure_operation_context_v1 as selection
from docs.experiments import frozen_feedback_v1 as guarded
from docs.experiments import predicate_runtime_compare_v1 as replay
from docs.experiments import system_comparison_v1 as baseline
from evals.process import run_process
from evals.runner import digest, snapshot
from evals.runtime import Events

previous = guarded.previous
TASKS = ('click-flag-default-map', 'more-range-membership', 'click-prompt-suffix')
POLICIES = ('current', 'operations')


def shared_payload(source):
    return json.loads(baseline.load(source / 'feedback-messages.json')[1]['content'])['public_check_feedback']


def worker(path):
    job = baseline.load(path)
    root = path.parent
    events = Events(root / 'trace.jsonl', job['policy'])
    provider = llm = None
    result = {'status': 'agent_error', 'published': False}
    try:
        config = previous.repair.config()
        previous.repair.check_identity(config)
        provider = previous.Provider('qwen', events)
        first = replay.SharedFirstProvider(provider, Path(job['shared_first']))
        llm = previous.CheckedBudgetLLM(first, config, events)

        def refresh(workspace, allowed, seeds):
            payload = shared_payload(Path(job['shared_first']))
            packed = selection.select(workspace, allowed, seeds, payload['test_code'], payload['observations'])
            previous.write_json(root / 'operation-selection.json', packed)
            return packed

        # Keep the public feedback text byte-identical, including sanitized path text.
        with patch.object(guarded, 'feedback', replay.shared_feedback):
            if job['policy'] == 'operations':
                with patch.object(previous, 'refresh_seeds', refresh):
                    result = guarded.run_candidate(llm, job, events)
            elif job['policy'] == 'current':
                result = guarded.run_candidate(llm, job, events)
            else:
                raise ValueError('Unknown policy')
        if digest(snapshot(root / 'initial-workspace')) != job['shared_candidate_hash']:
            raise ValueError('Shared initial candidate mismatch')
        previous.repair.check_identity(config)
    except Exception as exc:  # noqa: BLE001 - keep failures and rollback local source
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


def summarize(rows):
    return {p: {'tasks': len(rr := [r for r in rows if r['policy'] == p]),
                'passed': sum(r['accepted'] for r in rr),
                'new_calls': sum(r['worker'].get('new_model_calls', 0) for r in rr),
                'new_tokens': sum(r['worker'].get('new_model_tokens', 0) for r in rr),
                'budget_tokens_including_replay': sum((r['worker'].get('metrics') or {}).get('budget_accounted_tokens', 0)
                                                     for r in rr),
                'missing_worker_results': sum(r['worker'].get('metrics') is None for r in rr)} for p in POLICIES}


def run(output, offline_only=False):
    source = baseline.BASE / 'system-comparison-v1-rerun'
    manifest = baseline.load(source / 'manifest.json')
    baseline.intact(manifest)
    if not baseline.load(source / 'experiment.json')['complete']:
        raise ValueError('Completed frozen comparison required')
    cases = [next(c for c in manifest['cases'] if c['task_id'] == t) for t in TASKS]
    protected = [source.resolve()] + [Path(c[k]).resolve() for c in manifest['cases']
                                      for k in ('before', 'after', 'checks', 'harness', 'frozen_harness')]
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('Fresh nonoverlapping output required')
    if any(c['split'] != 'development' for c in cases):
        raise ValueError('Development only')
    output.mkdir(parents=True)
    inputs = [source / 'manifest.json', source / 'experiment.json', Path(__file__), Path(selection.__file__),
              Path(replay.__file__), Path(guarded.__file__), Path(previous.__file__)]
    for c in cases:
        root = source / 'runs' / c['task_id'] / 'full'
        inputs += [root / name for name in ('initial-messages.json', 'initial-response.txt',
                                            'feedback-messages.json', 'worker-result.json')]
    hashes = {str(p.resolve()): previous.admission.history.sha(p) for p in inputs}
    report = {'complete': False, 'offline_only': offline_only, 'runs': [], 'offline': [], 'protocol': {
        'name': 'failure-operation-v1', 'tasks': TASKS, 'policies': POLICIES, 'input_hashes': hashes,
        'config': previous.repair.config().to_dict(),
        'change': 'Only second-round source fragments; operation resolution and reverse caller ranking from public failures',
        'shared': 'Historical first request and response replayed and charged to both budgets; identical public feedback',
        'caps': '2 calls including replay, 15000 tokens, 2048 output, 5 complete functions/6000 chars; 600s worker',
        'selection': 'Two audited known development coverage gaps and one known failure with relevant code already shown',
        'limits': 'Not a blind/generalization experiment; framework flag lexical heuristic and incomplete static type resolution',
        'default_changed': False}}

    def intact():
        baseline.intact(manifest)
        if any(previous.admission.history.sha(Path(p)) != value for p, value in hashes.items()):
            raise ValueError('Frozen input changed')
        for c in cases:
            root = source / 'runs' / c['task_id'] / 'full'
            original_job = baseline.load(root / 'job.json')
            if digest(snapshot(root / 'original-workspace')) != original_job['original_hash']:
                raise ValueError('Historical original changed')
            if snapshot(root / 'initial-staging') != snapshot(root / 'initial-workspace'):
                raise ValueError('Historical initial snapshot changed')

    def save():
        report['summary'] = summarize(report['runs'])
        previous.write_json(output / 'experiment.json', report)

    for case in cases:
        root = source / 'runs' / case['task_id'] / 'full'
        result = baseline.load(root / 'worker-result.json')
        if result['initial']['status'] != 'completed' or result.get('feedback_attempts') != 1:
            raise ValueError('Completed first candidate and recorded feedback required')
        current = root / 'initial-workspace'
        payload = shared_payload(root)
        original = selection.REFRESH(current, case['allowed_files'], case['evidence'])
        packed = selection.select(current, case['allowed_files'], case['evidence'],
                                  payload['test_code'], payload['observations'])
        report['offline'].append({'task_id': case['task_id'], 'shared_candidate_hash': digest(snapshot(current)),
                                  'current': original, 'operations': packed,
                                  'fragments_changed': original['evidence'] != packed['evidence']})
        print(case['task_id'], 'offline', [r['symbol'] for r in packed['evidence']], flush=True)
    intact()
    save()
    if offline_only:
        report['complete'] = True
        save()
        return
    previous.repair.check_identity(previous.repair.config())
    for number, case in enumerate(cases):
        for policy in POLICIES[::1 if number % 2 == 0 else -1]:
            intact()
            root = output / case['task_id'] / policy
            workspace = root / 'workspace'
            shutil.copytree(case['before'], workspace)
            shared = source / 'runs' / case['task_id'] / 'full'
            initial_hash = digest(snapshot(shared / 'initial-workspace'))
            job = {k: case[k] for k in ('description', 'allowed_files', 'package', 'source_root', 'evidence',
                                      'description_hash', 'harness', 'harness_hash', 'frozen_harness', 'frozen_harness_hash')}
            job.update(workspace=str(workspace), original_hash=case['before_hash'], policy=policy,
                       shared_first=str(shared), shared_candidate_hash=initial_hash)
            previous.write_json(root / 'job.json', job)
            process = run_process([sys.executable, '-B', '-m', 'docs.experiments.failure_operation_compare_v1',
                                   '--worker', str(root / 'job.json')], baseline.ROOT, 600,
                                  root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                                  dict(os.environ, PYTHONPATH=str(baseline.ROOT), PYTHONDONTWRITEBYTECODE='1',
                                       PYTHONIOENCODING='utf-8'))
            path = root / 'worker-result.json'
            result = baseline.load(path) if path.exists() and not process['timed_out'] else {
                'status': 'worker_failed', 'metrics': None, 'published': False}
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
    parser.add_argument('--offline-only', action='store_true')
    args = parser.parse_args()
    if args.worker:
        worker(args.worker.resolve())
    elif args.output:
        run(args.output.resolve(), args.offline_only)
    else:
        parser.error('Require --output or --worker')
