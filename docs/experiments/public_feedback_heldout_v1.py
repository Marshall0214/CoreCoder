"""Validate the frozen development policy on all 20 heldout tasks, without tuning."""
import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import public_feedback_heldout_cases_v1 as examples
from docs.experiments import public_feedback_v2 as policy
from evals.process import run_process
from evals.runner import digest, snapshot


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def require_development(path):
    data = load(path)
    if not data['complete'] or not data['gate_passed'] or len(data['runs']) != 60:
        raise ValueError('Require the completed, eligible frozen development experiment')
    for name, value in data['protocol']['frozen_inputs'].items():
        if policy.admission.history.sha(Path(name)) != value:
            raise ValueError('Frozen development policy/input changed: ' + name)
    if data['protocol']['config'] != policy.repair.config().to_dict():
        raise ValueError('Repair settings changed')
    return data


def cases_from(admitted):
    data = load(admitted)
    cases = [c for c in data['cases'] if c['split'] == 'heldout']
    if not data['complete'] or len(cases) != 20 or {c['task_id'] for c in cases} != set(examples.CASES):
        raise ValueError('Require all fixed 20 unique heldout tasks')
    return cases


def fresh_output(output, cases, harnesses=()):
    if output.exists():
        raise ValueError('Fresh output required')
    roots = [Path(c[key]).resolve() for c in cases for key in ('before', 'after', 'checks')]
    roots += [Path(p).resolve() for p in harnesses]
    if any(output.resolve().is_relative_to(p) or p.is_relative_to(output.resolve()) for p in roots):
        raise ValueError('Output overlaps frozen source/checks')
    output.mkdir(parents=True)


def certify(admitted, development, output):
    require_development(development)
    cases = cases_from(admitted)
    fresh_output(output, cases)
    report = {'complete': False, 'model_calls': 0, 'cases': [], 'split': 'heldout',
              'authoring': 'handwritten from descriptions/original APIs; earlier retrieval outcomes seen; not blind',
              'reference_use': 'offline certification only; no reference/private grading code in repair input',
              'admission_hash': policy.admission.history.sha(admitted),
              'development_hash': policy.admission.history.sha(development),
              'examples_hash': policy.admission.history.sha(Path(examples.__file__))}
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
            outcomes[label] = policy.public_check(case[label], harness, case['package'], case['source_root'],
                                                 output / case['task_id'] / label)
        accepted = policy.certified(outcomes)
        report['cases'].append({'task_id': case['task_id'], 'certified': accepted,
                                'description_hash': hashlib.sha256(case['description'].encode()).hexdigest(),
                                'harness': str(harness.resolve()), 'harness_hash': digest(snapshot(harness)),
                                'outcomes': outcomes})
        policy.write_json(output / 'certificates.json', report)
        print(case['task_id'], 'certified' if accepted else 'REJECTED', flush=True)
    report['complete'] = all(c['certified'] for c in report['cases']) and len(report['cases']) == 20
    policy.write_json(output / 'certificates.json', report)


def paired(rows):
    pairs = {}
    for row in rows:
        group = pairs.setdefault(row['task_id'], {})
        if row['policy'] in group:
            raise ValueError('Duplicate pair')
        group[row['policy']] = row
    if any(set(p) != {'single', 'public-feedback'} for p in pairs.values()):
        raise ValueError('Incomplete pair')
    controls = lambda r: bool((r['verification'].get('groups') or {}).get('Controls', {}).get('passed'))
    return {'tasks': len(pairs),
            'gained': [t for t, p in pairs.items() if not p['single']['accepted'] and p['public-feedback']['accepted']],
            'lost': [t for t, p in pairs.items() if p['single']['accepted'] and not p['public-feedback']['accepted']],
            'new_control_failures': [t for t, p in pairs.items() if controls(p['single']) and not controls(p['public-feedback'])],
            'removed_control_failures': [t for t, p in pairs.items() if not controls(p['single']) and controls(p['public-feedback'])]}


def eligible(pair):
    return pair['tasks'] == 20 and len(pair['gained']) > len(pair['lost']) and not pair['new_control_failures']


def job_for(case, workspace, evidence, cert):
    # Only description, original/current source and certified public checks; no private task record.
    return dict({k: case[k] for k in ('description', 'allowed_files', 'package', 'source_root')},
                workspace=str(workspace), evidence=evidence, harness=cert['harness'], harness_hash=cert['harness_hash'])


def run(admitted, development, certificates, output):
    require_development(development)
    cases = cases_from(admitted)
    certs = load(certificates)
    if (not certs['complete'] or certs['admission_hash'] != policy.admission.history.sha(admitted)
            or certs['development_hash'] != policy.admission.history.sha(development)
            or certs['examples_hash'] != policy.admission.history.sha(Path(examples.__file__))):
        raise ValueError('Require certified frozen heldout checks for this policy')
    by_id = {c['task_id']: c for c in certs['cases']}
    if len(certs['cases']) != 20 or set(by_id) != set(examples.CASES) or not all(c['certified'] for c in by_id.values()):
        raise ValueError('Missing/duplicate heldout certificate')
    fresh_output(output, cases, [c['harness'] for c in by_id.values()])
    inputs = {str(p.resolve()): policy.admission.history.sha(p) for p in
              (admitted, development, certificates, Path(__file__), Path(examples.__file__))}
    # Guard the imported owned runtime, including provider/budget/parser/refresh helpers.
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
    report = {'complete': False, 'runs': [], 'protocol': {
        'name': 'public-feedback-heldout-v1', 'tasks': 20, 'split': 'heldout; no repair-policy tuning',
        'config': policy.repair.config().to_dict(), 'engine_hash': policy.repair.audit.ENGINE,
        'model_digest': policy.repair.MODEL_DIGEST, 'frozen_inputs': inputs,
        'worker': 'unchanged docs.experiments.public_feedback_v2.worker',
        'comparison': 'shared fresh initial patch vs at most one public correction; cumulative 15000 tokens',
        'adoption_gate': 'all 20 pairs complete; net gain positive; zero newly failing private Controls',
        'accounting': 'candidate total includes shared initial; never sum both arms',
        'authoring': certs['authoring'], 'reference_use': certs['reference_use'],
        'limits': 'already evaluated by prior retrieval experiments; hand-authored public checks; not new blind benchmark',
        'no_private_grader_input': True, 'default_agent_api_changed': False}}

    def frozen():
        require_development(development)
        policy.repair.check_identity(policy.repair.config())
        if any(policy.admission.history.sha(Path(p)) != value for p, value in inputs.items()):
            raise ValueError('Frozen runtime/input changed')
        for case in cases:
            for key in ('before', 'after', 'checks'):
                if digest(snapshot(Path(case[key]))) != case[key + '_hash']:
                    raise ValueError('Frozen source/private checks changed')
            cert = by_id[case['task_id']]
            if (digest(snapshot(Path(cert['harness']))) != cert['harness_hash'] or
                    cert['description_hash'] != hashlib.sha256(case['description'].encode()).hexdigest()):
                raise ValueError('Public checks/description changed')

    def save():
        report['summary'] = {p: policy.baseline.summarize([r for r in report['runs'] if r['policy'] == p])
                             for p in ('single', 'public-feedback')}
        report['pairs'] = paired(report['runs'])
        report['gate_passed'] = eligible(report['pairs'])
        policy.write_json(output / 'experiment.json', report)

    frozen()
    save()
    for case, observed in zip(cases, observations):
        frozen()
        root = output / case['task_id']
        root.mkdir()
        workspace = root / 'workspace'
        shutil.copytree(case['before'], workspace)
        path = root / 'job.json'
        policy.write_json(path, job_for(case, workspace, observed['evidence'], by_id[case['task_id']]))
        process = run_process([sys.executable, '-B', '-m', 'docs.experiments.public_feedback_v2', '--worker', str(path)],
                              workspace, 600, root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                              dict(os.environ, PYTHONPATH=str(policy.ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
        result_path = root / 'worker-result.json'
        result = load(result_path) if result_path.exists() and process['returncode'] == 0 and not process['timed_out'] else {
            'status': 'timeout' if process['timed_out'] else 'agent_error', 'metrics': None}
        for strategy, source in [('single', root / 'initial-workspace'), ('public-feedback', workspace)]:
            grade = root / ('grade-' + strategy)
            grade.mkdir()
            verified = policy.baseline.verify(case, source if source.exists() else workspace, grade)
            worker_result = dict(result)
            if strategy == 'single':
                worker_result.update(status=result.get('initial', {}).get('status', result['status']),
                                     metrics=result.get('initial_metrics'))
            accepted = worker_result['status'] == 'completed' and verified['passed']
            report['runs'].append({'task_id': case['task_id'], 'split': case['split'], 'repo': case['repo'],
                                  'policy': strategy, 'worker': worker_result, 'verification': verified,
                                  'accepted': accepted, 'status': 'passed' if accepted else 'failed_verification'
                                  if worker_result['status'] == 'completed' else worker_result['status'],
                                  'process': dict(process, seconds=result.get('initial_seconds', process['seconds']))
                                  if strategy == 'single' else process})
        save()
        print(case['task_id'], report['runs'][-2]['status'], '->', report['runs'][-1]['status'], flush=True)
    frozen()
    report['complete'] = len(report['runs']) == 40
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', required=True, type=Path)
    parser.add_argument('--development', required=True, type=Path)
    parser.add_argument('--certify', type=Path)
    parser.add_argument('--certificates', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.certify:
        certify(args.admission.resolve(), args.development.resolve(), args.certify.resolve())
    elif args.certificates and args.output:
        run(args.admission.resolve(), args.development.resolve(), args.certificates.resolve(), args.output.resolve())
    else:
        parser.error('Provide --certify or --certificates and --output')
