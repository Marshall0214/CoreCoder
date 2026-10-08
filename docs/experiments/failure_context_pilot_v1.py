"""Paired public feedback with unchanged budgets and failure-directed second context."""
import argparse
import copy
import hashlib
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import anchor_public_development_v1 as development
from docs.experiments import failure_context_v1 as selection
from docs.experiments.public_feedback_v2 import refresh_seeds
from evals.process import run_process
from evals.runner import digest, snapshot
from evals.runtime import Events

previous, policy = development.previous, development.policy
STRATEGIES = ('refreshed-seeds', 'failure-context')
TASKS = {'itsdangerous-none-salt', 'more-range-membership', 'boltons-chunked-bytes'}


def selected(admitted):
    return [c for c in development.development(admitted) if c['task_id'] in TASKS]


def paired(rows, workers):
    groups = {}
    for row in rows:
        group = groups.setdefault(row['task_id'], {})
        if row['policy'] in group:
            raise ValueError('Duplicate paired row')
        group[row['policy']] = row
    full = {t: p for t, p in groups.items() if set(p) == set(STRATEGIES)}
    controls = lambda r: bool((r['verification'].get('groups') or {}).get('Controls', {}).get('passed'))
    gained = [t for t, p in full.items() if not p['refreshed-seeds']['accepted'] and p['failure-context']['accepted']]
    lost = [t for t, p in full.items() if p['refreshed-seeds']['accepted'] and not p['failure-context']['accepted']]
    regressions = [t for t, p in full.items() if controls(p['refreshed-seeds']) and not controls(p['failure-context'])]
    finished = len(full) == 3 and len(rows) == 6 and len(workers) == 3
    return {'complete_pairs': len(full), 'gained': gained, 'lost': lost, 'new_control_failures': regressions,
            'gate_passed': finished and len(gained) > len(lost) and not regressions,
            'scope': 'known-case pilot, not overall development or heldout gain'}


def worker(path):
    job, root = previous.load(path), path.parent
    events = Events(root / 'trace.jsonl', 'failure-context-pilot-v1')
    provider = llm = None
    report = {'status': 'agent_error', 'branches': {}}
    try:
        policy.repair.check_identity(policy.repair.config())
        workspace, harness = Path(job['workspace']), Path(job['harness'])
        if digest(snapshot(harness)) != job['harness_hash']:
            raise ValueError('Public harness changed')
        provider = policy.Provider('qwen', events)
        llm = policy.CheckedBudgetLLM(provider, policy.repair.config(), events)
        first = policy.request(llm, workspace, job, job['evidence'], root, 'initial')
        report.update(initial=first, initial_metrics=llm.metrics(), initial_provider_calls=copy.deepcopy(provider.calls))
        shutil.copytree(workspace, root / 'initial-workspace')
        checked, feedback, packed = None, None, None
        if first['status'] == 'completed':
            checked = policy.public_check(workspace, harness, job['package'], job['source_root'], root / 'public-initial')
            report['public_initial'] = checked
            executable = all(not g['timed_out'] and g.get('tests_run', 0) > 0 and
                             not any(g.get(k, 0) for k in ('skipped', 'expected_failures', 'unexpected_successes'))
                             for g in checked.values())
            if not policy.all_pass(checked) and executable:
                baseline = refresh_seeds(workspace, job['allowed_files'], job['evidence'])['evidence']
                code = (harness / 'test_admission.py').read_text(encoding='utf-8')
                stderr = '\n'.join((root / 'public-initial' / (g + '.stderr.txt')).read_text(encoding='utf-8')
                                   for g in checked if not checked[g]['passed'])
                packed = selection.context(workspace, job['allowed_files'], baseline, code, stderr)
                feedback = {'provenance': 'certified handwritten public-description checks; not private scoring',
                            'test_code': code, 'observations': policy.diagnostic(checked, root / 'public-initial', workspace, harness)}
                report['selection'] = packed['metadata']
        for strategy in STRATEGIES:
            branch = root / strategy
            branch.mkdir()
            candidate = branch / 'workspace'
            shutil.copytree(workspace, candidate)
            branch_events = Events(branch / 'trace.jsonl', strategy)
            branch_provider = policy.Provider('qwen', branch_events)
            branch_llm = copy.copy(llm)
            branch_llm.inner, branch_llm.events = branch_provider, branch_events
            try:
                result = dict(first)
                if feedback:
                    evidence = baseline if strategy == 'refreshed-seeds' else packed['evidence']
                    # Current byte-identical copy has the same source hashes and line ranges.
                    result = policy.request(branch_llm, candidate, job, evidence, branch, 'feedback', feedback)
                    result['correction_status'] = result['status']
                    result['evidence_symbols'] = [r['symbol'] for r in evidence]
                    retained = False
                    if result['status'] == 'completed':
                        try:
                            result['public_corrected'] = policy.public_check(candidate, harness, job['package'], job['source_root'],
                                                                            branch / 'public-corrected')
                            retained = policy.all_pass(result['public_corrected'])
                        except Exception as exc:  # noqa: BLE001 - restore on failed validation
                            result['public_error'] = f'{type(exc).__name__}: {exc}'
                    result['correction_retained'] = retained
                    if not retained:
                        for name in job['allowed_files']:
                            (candidate / name).write_bytes((root / 'initial-workspace' / name).read_bytes())
                        result['status'] = first['status']
                result['metrics'] = branch_llm.metrics()
                result['provider_calls'] = branch_provider.calls
                report['branches'][strategy] = result
            finally:
                branch_provider.client.close()
        policy.repair.check_identity(policy.repair.config())
        report['status'] = 'completed'
    except Exception as exc:  # noqa: BLE001 - preserve experiment failures
        report.update(status='agent_error', error=f'{type(exc).__name__}: {exc}')
    finally:
        policy.write_json(root / 'worker-result.json', events.clean(report))
        if provider:
            provider.client.close()


def run(admitted, certificates, output):
    cases, certs = selected(admitted), previous.load(certificates)
    by_id = {c['task_id']: c for c in certs['cases']}
    if (not certs['complete'] or len(certs['cases']) != 30 or len(by_id) != 30 or set(by_id) != set(policy.examples.CASES) or
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
        'name': 'failure-context-pilot-v1', 'scope': 'two known development evidence gaps and one previously recovered control; not blind',
        'intervention': 'only reselect second-round functions from public traceback and membership calls',
        'stop_gate': 'all three pairs; net gain positive and no new Controls failures; then broader validation only',
        'config': policy.repair.config().to_dict(), 'max_calls_per_arm': 2, 'token_budget_per_arm': 15000,
        'comparison': 'shared fresh first patch; refreshed seeds vs failure-directed functions with identical public feedback',
        'retention': 'both arms keep correction only when both public groups pass; otherwise restore first snapshot',
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
        process = run_process([sys.executable, '-B', '-m', 'docs.experiments.failure_context_pilot_v1', '--worker', str(path)],
                              workspace, 600, root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                              dict(os.environ, PYTHONPATH=str(policy.ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
        result_path = root / 'worker-result.json'
        result = previous.load(result_path) if result_path.exists() and process['returncode'] == 0 and not process['timed_out'] else {
            'status': 'agent_error', 'branches': {}}
        report['actual_calls'].extend(result.get('initial_provider_calls', []))
        report['workers'].append({'task_id': case['task_id'], 'worker_status': result['status'],
                                  'initial': result.get('initial'), 'eligible': bool(result.get('selection')),
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
            report['runs'].append({'task_id': case['task_id'], 'split': 'known-development-diagnostic', 'repo': case['repo'],
                                  'policy': strategy, 'worker': chosen, 'verification': verified,
                                  'public_evaluation': checked, 'public_passed': policy.all_pass(checked),
                                  'accepted': accepted, 'status': 'passed' if accepted else 'failed_verification'
                                  if chosen['status'] == 'completed' else chosen['status'], 'process': process})
        save()
        print(case['task_id'], report['runs'][-2]['status'], '->', report['runs'][-1]['status'], flush=True)
    frozen()
    report['complete'] = len(report['runs']) == 6
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--admission', type=Path)
    parser.add_argument('--certificates', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker.resolve())
    elif args.admission and args.certificates and args.output:
        run(args.admission.resolve(), args.certificates.resolve(), args.output.resolve())
    else:
        parser.error('Provide worker or admission/certificates/output')
