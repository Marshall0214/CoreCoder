"""Freeze and test anchor/public recovery on all 30 existing development tasks."""
import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import anchor_public_recovery_v1 as adapter
from evals.process import run_process
from evals.runner import digest, snapshot

previous, policy = adapter.previous, adapter.policy
STRATEGIES = adapter.STRATEGIES


def development(admitted):
    data = previous.load(admitted)
    cases = [c for c in data['cases'] if c['split'] == 'development']
    ids = [c['task_id'] for c in cases]
    if not data['complete'] or len(cases) != 30 or len(set(ids)) != 30 or set(ids) != set(policy.examples.CASES):
        raise ValueError('Require all 30 fixed development tasks')
    return cases


def prior_coverage(source):
    data = previous.load(source)
    first = [r for r in data['runs'] if r['policy'] == 'single']
    if not data['complete'] or len(first) != 30 or len({r['task_id'] for r in first}) != 30:
        raise ValueError('Require completed prior 30-task development run')
    eligible = [r['task_id'] for r in first if r['worker']['status'] == 'invalid_patch' and
                r['worker'].get('initial', {}).get('error', '').endswith('Old text must match exactly once')]
    return {'tasks': len(first), 'prior_exact_match_failures': eligible,
            'source_sha256': policy.admission.history.sha(source), 'new_model_calls': 0}


def paired(rows, workers):
    groups = {}
    for row in rows:
        group = groups.setdefault(row['task_id'], {})
        if row['policy'] in group:
            raise ValueError('Duplicate strategy/task')
        group[row['policy']] = row
    complete = {t: p for t, p in groups.items() if set(p) == set(STRATEGIES)}
    controls = lambda r: bool((r['verification'].get('groups') or {}).get('Controls', {}).get('passed'))
    gained = [t for t, p in complete.items() if not p['anchor-only']['accepted'] and p['anchor-public']['accepted']]
    lost = [t for t, p in complete.items() if p['anchor-only']['accepted'] and not p['anchor-public']['accepted']]
    regressions = [t for t, p in complete.items() if controls(p['anchor-only']) and not controls(p['anchor-public'])]
    eligible = [w['task_id'] for w in workers if w['eligible']]
    finished = len(complete) == 30 and len(rows) == 60 and len(workers) == 30
    return {'complete_pairs': len(complete), 'eligible_tasks': eligible, 'eligible_count': len(eligible),
            'gained': gained, 'lost': lost, 'new_control_failures': regressions,
            'gate_passed': finished and bool(eligible) and len(gained) - len(lost) >= 2 and not regressions,
            'decision': 'incomplete' if not finished else 'no_trigger_coverage_stop_rollout' if not eligible else
                        'development_gain_requires_independent_validation' if len(gained) - len(lost) >= 2 and not regressions
                        else 'no_sufficient_gain_stop_rollout'}


def run(admitted, certificates, output):
    cases, certs = development(admitted), previous.load(certificates)
    by_id = {c['task_id']: c for c in certs['cases']}
    if (not certs['complete'] or len(certs['cases']) != 30 or len(by_id) != 30 or set(by_id) != {c['task_id'] for c in cases} or
            certs['admission_hash'] != policy.admission.history.sha(admitted) or
            certs['examples_hash'] != policy.admission.history.sha(Path(policy.examples.__file__)) or
            not all(c['certified'] for c in by_id.values())):
        raise ValueError('Require unchanged complete public certificates')
    previous.fresh_output(output, cases, [c['harness'] for c in by_id.values()])
    inputs = {str(p.resolve()): policy.admission.history.sha(p) for p in (admitted, certificates, Path(__file__))}
    inputs.update({str(Path(m.__file__).resolve()): policy.admission.history.sha(Path(m.__file__))
                   for name, m in list(sys.modules.items()) if name.startswith(('docs.experiments.', 'evals.', 'corecoder.'))
                   and getattr(m, '__file__', None) and Path(m.__file__).suffix == '.py'})
    observations = []
    for case in cases:
        index = policy.baseline.functions.FunctionIndex(Path(case['before']), case['allowed_files'])
        index.refresh()
        observations.append(dict(task_id=case['task_id'], **policy.retrieval.retrieve(index, case['description'])))
    policy.write_json(output / 'observations.json', observations)
    inputs[str(output / 'observations.json')] = policy.admission.history.sha(output / 'observations.json')
    report = {'complete': False, 'runs': [], 'workers': [], 'actual_calls': [], 'protocol': {
        'name': 'anchor-public-development-v1', 'scope': 'all fixed 30 development tasks; fresh pairing, no heldout',
        'intervention': 'unchanged known-case adapter; no extra semantic correction on completed initial patches',
        'stop_gate': 'complete 30 pairs; eligible > 0; net gain >= 2; no new Controls failures; otherwise stop rollout',
        'config': policy.repair.config().to_dict(), 'max_calls_per_arm': 2, 'token_budget_per_arm': 15000,
        'comparison': 'shared fresh first patch; anchor-only vs anchor+certified public feedback in sole resubmission',
        'retention': 'public arm retains correction only if Reproduce and Preserve pass; otherwise restores first snapshot',
        'accounting': 'actual calls count shared first once plus both new resubmissions; per-arm totals overlap',
        'unique_match_version_checks': 'unchanged', 'no_private_grader_input': True, 'frozen_inputs': inputs}}

    def frozen():
        policy.repair.check_identity(policy.repair.config())
        if any(policy.admission.history.sha(Path(p)) != h for p, h in inputs.items()):
            raise ValueError('Frozen runtime/input changed')
        for case in cases:
            for key in ('before', 'after', 'checks'):
                if digest(snapshot(Path(case[key]))) != case[key + '_hash']:
                    raise ValueError('Frozen source/grader changed')
            cert = by_id[case['task_id']]
            if (digest(snapshot(Path(cert['harness']))) != cert['harness_hash'] or
                    cert['description_hash'] != hashlib.sha256(case['description'].encode()).hexdigest()):
                raise ValueError('Public harness/description changed')

    def save():
        report['summary'] = {s: policy.baseline.summarize([r for r in report['runs'] if r['policy'] == s])
                             for s in STRATEGIES}
        report['actual_usage'] = {'model_calls': len(report['actual_calls']),
                                 'tokens': sum(c.get('total_tokens') or 0 for c in report['actual_calls']),
                                 'missing_usage_calls': sum(not c.get('total_tokens') for c in report['actual_calls'])}
        report['pairing'] = paired(report['runs'], report['workers'])
        policy.write_json(output / 'experiment.json', report)

    frozen()
    save()
    for case, observed in zip(cases, observations):
        frozen()
        root = output / case['task_id']
        root.mkdir()
        workspace = root / 'workspace'
        shutil.copytree(case['before'], workspace)
        job = previous.job_for(case, workspace, observed['evidence'], by_id[case['task_id']])
        path = root / 'job.json'
        policy.write_json(path, job)
        process = run_process([sys.executable, '-B', '-m', 'docs.experiments.anchor_public_recovery_v1', '--worker', str(path)],
                              workspace, 600, root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                              dict(os.environ, PYTHONPATH=str(policy.ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
        result_path = root / 'worker-result.json'
        result = previous.load(result_path) if result_path.exists() and process['returncode'] == 0 and not process['timed_out'] else {
            'status': 'agent_error', 'branches': {}}
        report['actual_calls'].extend(result.get('initial_provider_calls', []))
        report['workers'].append({'task_id': case['task_id'], 'worker_status': result['status'],
                                  'initial': result.get('initial'), 'eligible': bool(result.get('diagnosis')),
                                  'initial_metrics': result.get('initial_metrics')})
        for strategy in STRATEGIES:
            branch = root / strategy
            branch.mkdir(exist_ok=True)
            source = branch / 'workspace'
            chosen = result['branches'].get(strategy, {'status': 'agent_error', 'metrics': None})
            report['actual_calls'].extend(chosen.get('provider_calls', []))
            grade = root / ('grade-' + strategy)
            grade.mkdir()
            verified = policy.baseline.verify(case, source if source.exists() else workspace, grade)
            checked = policy.public_check(source if source.exists() else workspace, Path(job['harness']),
                                          case['package'], case['source_root'], root / ('public-final-' + strategy))
            accepted = chosen['status'] == 'completed' and verified['passed']
            report['runs'].append({'task_id': case['task_id'], 'split': 'development', 'repo': case['repo'],
                                  'policy': strategy, 'worker': chosen, 'verification': verified,
                                  'public_evaluation': checked, 'public_passed': policy.all_pass(checked),
                                  'accepted': accepted, 'status': 'passed' if accepted else 'failed_verification'
                                  if chosen['status'] == 'completed' else chosen['status'], 'process': process})
        save()
        print(case['task_id'], report['runs'][-2]['status'], '->', report['runs'][-1]['status'], flush=True)
    frozen()
    report['complete'] = len(report['runs']) == 60
    save()



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', required=True, type=Path)
    parser.add_argument('--certificates', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    run(args.admission.resolve(), args.certificates.resolve(), args.output.resolve())
