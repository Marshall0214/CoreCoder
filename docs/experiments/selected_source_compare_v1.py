"""Compare fixed seeds with model-selected source under the same token/evidence budget."""
import argparse
import os
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

from docs.experiments import deepseek_direct_provider_v1 as adapters
from docs.experiments import frozen_feedback_v1 as guarded
from docs.experiments import selected_source_repair_v1 as loop
from docs.experiments import system_comparison_v1 as baseline
from evals.process import run_process
from evals.runtime import Events

previous = guarded.previous
TASKS = ('click-usage-empty', 'more-predicate-sentinel')
POLICIES = ('fixed-seeds', 'model-selected')


def worker(path):
    job = baseline.load(path)
    root = path.parent
    events = Events(root / 'trace.jsonl', job['policy'])
    provider = llm = None
    started = time.monotonic()
    result = {'status': 'agent_error', 'published': False}
    try:
        previous.repair.check_identity(previous.repair.config())
        config = replace(previous.repair.config(), max_output_tokens=4096, output_policy='remaining',
                         model='deepseek-flash', base_url='https://api.deepseek.com')
        provider = adapters.Provider('deepseek-off', events)
        llm = adapters.CheckedBudgetLLM(provider, config, events)
        result = loop.run_candidate(llm, job, events)
        previous.repair.check_identity(previous.repair.config())
    except Exception as exc:  # noqa: BLE001 - preserve and score every failed attempt
        result.update(status='agent_error', error_type=type(exc).__name__, published=False)
        if (root / 'original-workspace').exists():
            guarded.restore(Path(job['workspace']), root / 'original-workspace', root)
    finally:
        result.update(metrics=llm.metrics() if llm else None, provider_calls=provider.calls if provider else [],
                      seconds=round(time.monotonic() - started, 4))
        previous.write_json(root / 'worker-result.json', events.clean(result))
        if provider:
            provider.close()


def summary(rows):
    return {p: {'tasks': len(rr := [r for r in rows if r['policy'] == p]),
                'passed': sum(r['accepted'] for r in rr),
                'controls_passed': sum(bool((r['verification'].get('groups') or {}).get('Controls', {}).get('passed')) for r in rr),
                'calls': sum((r['worker'].get('metrics') or {}).get('llm_calls', 0) for r in rr),
                'tokens': sum((r['worker'].get('metrics') or {}).get('budget_accounted_tokens', 0) for r in rr),
                'missing_worker_results': sum(r['worker'].get('metrics') is None for r in rr),
                'worker_seconds': round(sum(r['process']['seconds'] for r in rr), 4)} for p in POLICIES}


def run(output, scope):
    source = baseline.BASE / 'system-comparison-v1-rerun'
    manifest = baseline.load(source / 'manifest.json')
    history = baseline.load(source / 'experiment.json')
    baseline.intact(manifest)
    if not history['complete'] or history.get('aborted'):
        raise ValueError('Completed 150-run baseline required')
    cases = ([c for c in manifest['cases'] if c['split'] == 'development'] if scope == 'development' else
             list(manifest['cases']) if scope == 'full' else
             [next(c for c in manifest['cases'] if c['task_id'] == task) for task in TASKS])
    if scope != 'full' and any(c['split'] != 'development' for c in cases):
        raise ValueError('Development tasks only')
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Fresh nonoverlapping output required')
    for case in manifest['cases']:
        for key in ('before', 'after', 'checks', 'harness', 'frozen_harness'):
            p = Path(case[key]).resolve()
            if output.is_relative_to(p) or p.is_relative_to(output):
                raise ValueError('Output overlaps frozen sources or tests')
    output.mkdir(parents=True)
    paths = [source / 'manifest.json', source / 'experiment.json', Path(__file__), Path(guarded.__file__), Path(adapters.__file__), Path(loop.__file__), Path(loop.selection.__file__)]
    hashes = {str(p.resolve()): previous.admission.history.sha(p) for p in paths}
    report = {'complete': False, 'runs': [], 'protocol': {'name': 'selected-source-compare-v1', 'input_hashes': hashes,
              'tasks': [c['task_id'] for c in cases], 'scope': scope, 'policies': POLICIES,
              'config': replace(previous.repair.config(), model='deepseek-flash', base_url='https://api.deepseek.com', max_output_tokens=4096, output_policy='remaining').to_dict(),
              'providers': adapters.PROVIDERS,
              'request_settings': {'reasoning_effort': 'none', 'top_p': 0.95, 'response_format': 'json_object'},
              'selection': 'Fixed development pool or explicit known full pool; pilot is only a feasibility check',
              'change': 'One extra model source-selection call before up to two repair calls; AST signatures/docstrings from allowed original source only',
              'unchanged': 'Same model, first prompt, evidence, feedback, 15000 total token budget and 4096 output cap; two patch calls per arm; selected arm pays one extra selection call within the same budget',
              'limits': 'Known tasks; cloud alias not frozen weights; model, thinking and output changes cannot be attributed to a single factor',
              'order': 'Alternating arm order; fresh model requests'}}

    def intact():
        baseline.intact(manifest)
        if any(previous.admission.history.sha(Path(p)) != h for p, h in hashes.items()):
            raise ValueError('Frozen comparison source changed')

    def save():
        report['summary'] = summary(report['runs'])
        previous.write_json(output / 'experiment.json', report)

    report['protocol']['identity'] = adapters.identity()
    previous.repair.check_identity(previous.repair.config())
    save()
    for number, case in enumerate(cases):
        for policy in POLICIES[::1 if number % 2 == 0 else -1]:
            intact()
            root = output / case['task_id'] / policy
            workspace = root / 'workspace'
            shutil.copytree(case['before'], workspace)
            job = {k: case[k] for k in ('description', 'allowed_files', 'package', 'source_root', 'evidence',
                                      'description_hash', 'harness', 'harness_hash', 'frozen_harness', 'frozen_harness_hash')}
            job.update(workspace=str(workspace), original_hash=case['before_hash'], policy=policy, max_calls=2)
            previous.write_json(root / 'job.json', job)
            process = run_process([sys.executable, '-B', '-m', 'docs.experiments.selected_source_compare_v1', '--worker', str(root / 'job.json')],
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
            report['runs'].append({'task_id': case['task_id'], 'policy': policy, 'accepted': accepted,
                                   'worker': result, 'verification': verified, 'public': public, 'frozen': frozen, 'process': process})
            save()
            print(case['task_id'], policy, result['status'], 'accepted=', accepted, flush=True)
    intact()
    previous.repair.check_identity(previous.repair.config())
    report['complete'] = len(report['runs']) == len(cases) * len(POLICIES)
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--scope', choices=('pilot', 'development', 'full'), default='pilot')
    args = parser.parse_args()
    if args.worker:
        worker(args.worker.resolve())
    elif args.output:
        run(args.output.resolve(), args.scope)
    else:
        parser.error('Require --output or --worker')
