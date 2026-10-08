"""Thirty-task development experiment: shared first patch, one public correction.

No hidden test/answer enters the worker. Public checks must be certified before
inference; failed or unvalidated corrections retain the first candidate.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from docs.experiments import class_scoped_retrieval_v1 as retrieval
from docs.experiments import expanded_baseline_v2 as baseline
from docs.experiments import public_feedback_cases_v1 as examples
from docs.experiments.provider_compare_worker_v1 import CheckedBudgetLLM, Provider
from docs.experiments.repair_forwarding_worker_v1 import refresh_seeds
from evals.process import run_process, test_environment
from evals.runner import digest, snapshot
from evals.runtime import Events
from evals.symbol_context import apply_symbol_patch

ROOT = baseline.ROOT
admission = baseline.admission
repair = baseline.repair


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def public_check(source, harness, package, source_root, logs):
    """Isolated imports, nonempty groups, immutable source/checks, bounded runtime."""
    source, harness = Path(source), Path(harness)
    hashes = digest(snapshot(source)), digest(snapshot(harness))
    logs.mkdir(parents=True, exist_ok=False)
    results = {}
    for name in ('Reproduce', 'Preserve'):
        record = logs / (name + '.json')
        process = run_process(
            [str(admission.PYTHON), '-I', '-B', '-c', admission.previous.BOOT,
             str((source / source_root).resolve()), str(harness.resolve()), package, name, str(record.resolve())],
            source, 15, logs / (name + '.stdout.txt'), logs / (name + '.stderr.txt'), test_environment(source))
        score = json.loads(record.read_text()) if record.exists() else {}
        passed = (process['returncode'] == 0 and not process['timed_out'] and score.get('tests_run', 0) > 0
                  and score.get('successful') and not any(score.get(k, 0) for k in
                      ('skipped', 'expected_failures', 'unexpected_successes', 'errors', 'failures')))
        results[name] = dict(process, **score, passed=bool(passed))
    if hashes != (digest(snapshot(source)), digest(snapshot(harness))):
        raise ValueError('Public checks mutated source or harness')
    return results


def certified(outcomes):
    target = outcomes['before']['Reproduce']
    return (not target['passed'] and not target['timed_out'] and target.get('tests_run', 0) > 0
            and target.get('failures', 0) + target.get('errors', 0) > 0
            and outcomes['before']['Preserve']['passed']
            and all(group['passed'] for group in outcomes['after'].values()))


def certify(admitted, output):
    data = json.loads(admitted.read_text())
    cases = [c for c in data['cases'] if c['split'] == 'development']
    if not data['complete'] or len(cases) != 30 or {c['task_id'] for c in cases} != set(examples.CASES):
        raise ValueError('Require the fixed 30 development tasks')
    if output.exists():
        raise ValueError('Fresh certificate output required')
    if any(output.resolve().is_relative_to(Path(c[key]).resolve()) for c in cases
           for key in ('before', 'after', 'checks')):
        raise ValueError('Output overlaps frozen input')
    output.mkdir(parents=True)
    report = {'complete': False, 'model_calls': 0, 'cases': [],
              'authoring': 'handwritten from descriptions/original APIs; author exposed to earlier outcomes; not blind',
              'reference_use': 'offline certification only; no reference code/private tests in model input',
              'admission_hash': admission.history.sha(admitted), 'examples_hash': admission.history.sha(Path(examples.__file__))}
    for case in cases:
        harness = output / case['task_id'] / 'checks'
        harness.mkdir(parents=True)
        code = examples.code(case['task_id'])
        compile(code, 'test_admission.py', 'exec')
        (harness / 'test_admission.py').write_text(code, encoding='utf-8')
        outcomes = {}
        for label in ('before', 'after'):
            if digest(snapshot(Path(case[label]))) != case[label + '_hash']:
                raise ValueError('Frozen source changed')
            outcomes[label] = public_check(case[label], harness, case['package'], case['source_root'],
                                          output / case['task_id'] / label)
        report['cases'].append({'task_id': case['task_id'], 'certified': certified(outcomes),
                                'description_hash': hashlib.sha256(case['description'].encode()).hexdigest(),
                                'harness': str(harness.resolve()), 'harness_hash': digest(snapshot(harness)),
                                'outcomes': outcomes})
        write_json(output / 'certificates.json', report)
        print(case['task_id'], 'certified' if certified(outcomes) else 'REJECTED', flush=True)
    report['complete'] = len(report['cases']) == 30 and all(c['certified'] for c in report['cases'])
    write_json(output / 'certificates.json', report)


def diagnostic(outcomes, logs, workspace, harness):
    parts = []
    for name, outcome in outcomes.items():
        if not outcome['passed']:
            value = (logs / (name + '.stderr.txt')).read_text(encoding='utf-8', errors='replace')
            value = value.replace(str(workspace), '<candidate>').replace(str(harness), '<public-checks>')
            # Keep assertion details rather than the discovery preamble; bounded public feedback.
            parts.append(name + ':\n' + value[-2200:])
    return '\n'.join(parts)[:4400]


def all_pass(outcomes):
    return all(g['passed'] for g in outcomes.values())


def request(llm, workspace, job, evidence, root, stage, feedback=None):
    """Same first prompt as class-scoped baseline; only feedback extends round two."""
    repair.validate_evidence(workspace, job['allowed_files'], evidence)
    system = repair.patcher.SYMBOL_SYSTEM
    payload = {'description': job['description'], 'allowed_files': job['allowed_files'], 'fragments': evidence}
    if feedback is not None:
        system += (' These public development checks are not the final grader. Repair only source, '
                   'preserve normal behavior, and check expectations against the description. '
                   'Fragments are the current candidate; use current hashes and symbols. '
                   'Return one complete structured patch, not explanations.')
        payload['public_check_feedback'] = feedback
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
    write_json(root / (stage + '-messages.json'), messages)
    result = {'status': 'invalid_patch', 'prompt_hash': hashlib.sha256(
        json.dumps(messages, ensure_ascii=False).encode()).hexdigest()}
    stage_workspace = root / (stage + '-staging')
    try:
        response = llm.chat(messages, tools=[])
        (root / (stage + '-response.txt')).write_text(response.content, encoding='utf-8')
        if response.tool_calls:
            raise ValueError('Unexpected tool call')
        # Atomic at the workflow level: malformed corrections cannot damage the first patch.
        shutil.copytree(workspace, stage_workspace)
        edited = apply_symbol_patch(baseline.envelope.normalize(response.content), stage_workspace,
                                    job['allowed_files'], evidence)
        for name in edited:
            compile((stage_workspace / name).read_bytes(), name, 'exec')
        for name in edited:
            (workspace / name).write_bytes((stage_workspace / name).read_bytes())
        result.update(status='completed', edited_files=edited)
    except Exception as exc:  # noqa: BLE001 - retain failed provider, budget and patch attempts
        result.update(status=str(exc) if isinstance(exc, baseline.InvalidCompletion)
                      else 'budget_exceeded' if isinstance(exc, baseline.BudgetExceeded) else 'invalid_patch',
                      error=f'{type(exc).__name__}: {exc}')
    return result


def worker(path):
    job = json.loads(path.read_text(encoding='utf-8'))
    root = path.parent
    events = Events(root / 'trace.jsonl', 'public-feedback-v2')
    provider = llm = None
    result = {'status': 'agent_error', 'feedback_attempts': 0}
    started = time.monotonic()
    try:
        repair.check_identity(repair.config())
        workspace, harness = Path(job['workspace']), Path(job['harness'])
        if digest(snapshot(harness)) != job['harness_hash']:
            raise ValueError('Public harness changed')
        provider = Provider('qwen', events)
        llm = CheckedBudgetLLM(provider, repair.config(), events)
        first = request(llm, workspace, job, job['evidence'], root, 'initial')
        result.update(status=first['status'], initial=first, initial_metrics=llm.metrics().copy(),
                      initial_seconds=round(time.monotonic() - started, 4))
        shutil.copytree(workspace, root / 'initial-workspace')
        if first['status'] == 'completed':
            checked = public_check(workspace, harness, job['package'], job['source_root'], root / 'public-initial')
            result['public_initial'] = checked
            # Runtime errors in a certified check also expose a source defect; harness failures do not qualify.
            executable = all(not g['timed_out'] and g.get('tests_run', 0) > 0 and
                             not any(g.get(k, 0) for k in ('skipped', 'expected_failures', 'unexpected_successes'))
                             for g in checked.values())
            if not all_pass(checked) and executable:
                evidence = refresh_seeds(workspace, job['allowed_files'], job['evidence'])['evidence']
                feedback = {'provenance': 'certified handwritten public-description checks; not private scoring',
                            'test_code': (harness / 'test_admission.py').read_text(encoding='utf-8'),
                            'observations': diagnostic(checked, root / 'public-initial', workspace, harness)}
                result['feedback_attempts'] = 1
                second = request(llm, workspace, job, evidence, root, 'feedback', feedback)
                result['correction'] = second
                accepted = False
                if second['status'] == 'completed':
                    result['public_corrected'] = public_check(workspace, harness, job['package'], job['source_root'],
                                                              root / 'public-corrected')
                    accepted = all_pass(result['public_corrected'])
                result['correction_retained'] = accepted
                if not accepted:
                    for name in job['allowed_files']:
                        (workspace / name).write_bytes((root / 'initial-workspace' / name).read_bytes())
            else:
                result['feedback_skipped'] = 'checks_passed' if all_pass(checked) else 'public_execution_failure'
        else:
            result['feedback_skipped'] = 'initial_not_completed'
        repair.check_identity(repair.config())
    except Exception as exc:  # noqa: BLE001 - preserve experiment failures
        result.update(status='agent_error', error=f'{type(exc).__name__}: {exc}')
    finally:
        result['metrics'] = llm.metrics() if llm else None
        result['provider_calls'] = provider.calls if provider else []
        write_json(root / 'worker-result.json', events.clean(result))
        if provider:
            provider.client.close()


def run(admitted, certificates, output):
    data = json.loads(admitted.read_text())
    certs = json.loads(certificates.read_text())
    cases = [c for c in data['cases'] if c['split'] == 'development']
    if (not certs['complete'] or len(cases) != 30 or
            certs['admission_hash'] != admission.history.sha(admitted) or
            certs['examples_hash'] != admission.history.sha(Path(examples.__file__))):
        raise ValueError('All development checks must be certified against these frozen inputs')
    by_id = {c['task_id']: c for c in certs['cases']}
    if set(by_id) != {c['task_id'] for c in cases} or not all(c['certified'] for c in by_id.values()):
        raise ValueError('Incomplete/duplicate certificate set')
    if output.exists():
        raise ValueError('Fresh experiment output required')
    if any(output.resolve().is_relative_to(Path(c[key]).resolve()) for c in cases
           for key in ('before', 'after', 'checks')) or any(
               output.resolve().is_relative_to(Path(c['harness']).resolve()) for c in by_id.values()):
        raise ValueError('Output overlaps frozen input')
    output.mkdir(parents=True)
    inputs = {str(p.resolve()): admission.history.sha(p) for p in
              (admitted, certificates, Path(__file__), Path(examples.__file__), Path(retrieval.__file__),
               Path(baseline.__file__), Path(sys.modules[refresh_seeds.__module__].__file__))}
    observations = []
    for case in cases:
        index = baseline.functions.FunctionIndex(Path(case['before']), case['allowed_files'])
        index.refresh()
        observations.append(dict(task_id=case['task_id'], **retrieval.retrieve(index, case['description'])))
    write_json(output / 'observations.json', observations)
    inputs[str(output / 'observations.json')] = admission.history.sha(output / 'observations.json')
    report = {'complete': False, 'runs': [], 'protocol': {
        'name': 'public-feedback-v2', 'tasks': 30, 'split': 'development only; heldout not consulted',
        'config': repair.config().to_dict(), 'model_digest': repair.MODEL_DIGEST, 'engine_hash': repair.audit.ENGINE,
        'comparison': 'one shared fresh initial call per task; control snapshot vs optional correction',
        'feedback': 'at most one correction; cumulative 15000 tokens; same <=6000-char refreshed seeds; no tools',
        'retention': 'keep correction only if Reproduce and Preserve pass; otherwise retain initial patch',
        'accounting': 'initial calls overlap both arms; actual usage is candidate cumulative usage, not sum of arms',
        'authoring': certs['authoring'], 'reference_use': certs['reference_use'],
        'stop_gate': 'development net gain >=2, controls not worse; otherwise stop this policy; no heldout this run',
        'frozen_inputs': inputs, 'no_private_grader_input': True}}

    def frozen():
        repair.check_identity(repair.config())
        if any(admission.history.sha(Path(p)) != value for p, value in inputs.items()):
            raise ValueError('Frozen adapter/input changed')
        for case in cases:
            for key in ('before', 'after', 'checks'):
                if digest(snapshot(Path(case[key]))) != case[key + '_hash']:
                    raise ValueError('Frozen source/private tests changed')
            cert = by_id[case['task_id']]
            if (digest(snapshot(Path(cert['harness']))) != cert['harness_hash'] or
                    cert['description_hash'] != hashlib.sha256(case['description'].encode()).hexdigest()):
                raise ValueError('Public harness/description changed')

    def save():
        report['summary'] = {p: baseline.summarize([r for r in report['runs'] if r['policy'] == p])
                             for p in ('single', 'public-feedback')}
        pairs = {p: {r['task_id']: r for r in report['runs'] if r['policy'] == p}
                 for p in ('single', 'public-feedback')}
        report['gained'] = [t for t in pairs['single'] if not pairs['single'][t]['accepted'] and
                            pairs['public-feedback'][t]['accepted']]
        report['lost'] = [t for t in pairs['single'] if pairs['single'][t]['accepted'] and
                          not pairs['public-feedback'][t]['accepted']]
        stats = report['summary']
        report['gate_passed'] = (stats['public-feedback']['overall']['passed'] - stats['single']['overall']['passed'] >= 2
                                and stats['public-feedback']['overall']['controls_passed'] >=
                                stats['single']['overall']['controls_passed'])
        write_json(output / 'experiment.json', report)

    frozen()
    save()
    for case, observed in zip(cases, observations):
        frozen()
        root = output / case['task_id']
        root.mkdir()
        workspace = root / 'workspace'
        shutil.copytree(case['before'], workspace)
        cert = by_id[case['task_id']]
        # Deliberately no task record, after snapshot or private grading directory in the job.
        job = {k: case[k] for k in ('description', 'allowed_files', 'package', 'source_root')}
        job.update(workspace=str(workspace), evidence=observed['evidence'],
                   harness=cert['harness'], harness_hash=cert['harness_hash'])
        path = root / 'job.json'
        write_json(path, job)
        process = run_process([sys.executable, '-B', '-m', 'docs.experiments.public_feedback_v2', '--worker', str(path)],
                              workspace, 600, root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                              dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
        result_path = root / 'worker-result.json'
        result = json.loads(result_path.read_text()) if result_path.exists() and not process['timed_out'] else {
            'status': 'timeout' if process['timed_out'] else 'agent_error', 'metrics': None}
        for policy, source in [('single', root / 'initial-workspace'), ('public-feedback', workspace)]:
            grade = root / ('grade-' + policy)
            grade.mkdir()
            verified = baseline.verify(case, source if source.exists() else workspace, grade)
            worker_result = dict(result)
            if policy == 'single':
                worker_result.update(status=result.get('initial', {}).get('status', result['status']),
                                     metrics=result.get('initial_metrics'))
            accepted = worker_result['status'] == 'completed' and verified['passed']
            report['runs'].append({'task_id': case['task_id'], 'split': case['split'], 'repo': case['repo'],
                                  'policy': policy, 'worker': worker_result, 'verification': verified,
                                  'accepted': accepted, 'status': 'passed' if accepted else 'failed_verification'
                                  if worker_result['status'] == 'completed' else worker_result['status'],
                                  'process': dict(process, seconds=result.get('initial_seconds', process['seconds']))
                                  if policy == 'single' else process})
        save()
        print(case['task_id'], report['runs'][-2]['status'], '->', report['runs'][-1]['status'],
              'feedback', result.get('feedback_attempts', 0), flush=True)
    frozen()
    report['complete'] = len(report['runs']) == 60
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--admission', type=Path)
    parser.add_argument('--certificates', type=Path)
    parser.add_argument('--certify', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker.resolve())
    elif args.admission and args.certify:
        certify(args.admission.resolve(), args.certify.resolve())
    elif args.admission and args.certificates and args.output:
        run(args.admission.resolve(), args.certificates.resolve(), args.output.resolve())
    else:
        parser.error('Supply --worker, or --admission with --certify, or --admission/--certificates/--output')
