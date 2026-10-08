"""Freeze and run all 50 tasks across original, retrieval-only and full workflows."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from docs.experiments import click_resource_repair_v2 as context
from docs.experiments import system_comparison_worker_v1 as worker
from evals.process import run_process
from evals.runner import digest, snapshot

previous = worker.previous
POLICIES = ('original', 'retrieval', 'full')
UPSTREAM_REF = '84b320e2d21628a2c00934aa0a2343139c16a49e'
ROOT = previous.ROOT
BASE = ROOT / '.tmp' / 'real-defects'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def extract_engine(output):
    names = subprocess.run(['git', 'ls-tree', '-r', '--name-only', UPSTREAM_REF, 'corecoder'], cwd=ROOT,
                           check=True, capture_output=True, text=True).stdout.splitlines()
    if not names or any(not n.startswith('corecoder/') or '..' in Path(n).parts for n in names):
        raise ValueError('Invalid upstream source paths')
    for name in names:
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = subprocess.run(['git', 'show', UPSTREAM_REF + ':' + name], cwd=ROOT,
                              check=True, capture_output=True).stdout
        path.write_bytes(data)
    return output / 'corecoder'


def inputs():
    return {
        'admission': BASE / 'expanded-admission-v2-final/admission.json',
        'development_certificate': BASE / 'public-feedback-v2-certification-final/certificates.json',
        'heldout_certificate': BASE / 'public-feedback-heldout-v1-certification-final/certificates.json',
        'frozen': BASE / 'frozen-assertion-audit-v1-certified/audit.json',
        'product': BASE / 'fixed-product-checks-v1-certification/certificate.json',
        'context': BASE / 'click-resource-repair-v2/certificate.json',
    }


def prepare(output):
    paths = inputs()
    data = {k: load(p) for k, p in paths.items()}
    cases = data['admission']['cases']
    if len(cases) != 50 or len({c['task_id'] for c in cases}) != 50 or not data['admission']['complete']:
        raise ValueError('Require complete fixed 50 tasks')
    for name in ('development_certificate', 'heldout_certificate', 'frozen', 'product'):
        if not data[name]['complete']:
            raise ValueError('Incomplete certificates')
    if not data['context']['certified']:
        raise ValueError('Context v2 checks uncertified')
    certs = {c['task_id']: c for key in ('development_certificate', 'heldout_certificate') for c in data[key]['cases']}
    guards = {c['task_id']: c for c in data['frozen']['cases'] if c['certified']}
    if len(certs) != 50 or len(guards) != 44 or not all(c['certified'] for c in certs.values()):
        raise ValueError('Missing or duplicate certification')
    roots = [Path(c[k]).resolve() for c in cases for k in ('before', 'after', 'checks')]
    roots += [BASE / 'fixed-product-checks-v1-certification', BASE / 'click-resource-repair-v2']
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in roots):
        raise ValueError('Fresh output outside frozen inputs required')
    output.mkdir(parents=True)
    engine = extract_engine(output / 'upstream')
    hashes = {str(p.resolve()): previous.admission.history.sha(p) for p in [*paths.values(), Path(__file__), Path(worker.__file__),
                                                                        Path(context.__file__), Path(worker.guarded.__file__), Path(previous.__file__)]}
    manifest = {'complete': False, 'cases': [], 'upstream': str(engine), 'upstream_hash': digest(snapshot(engine)),
                'protocol': {'name': 'system-comparison-v1', 'upstream_ref': UPSTREAM_REF, 'tasks': 50,
                             'policies': POLICIES, 'config': previous.repair.config().to_dict(),
                             'model_digest': previous.repair.MODEL_DIGEST, 'input_hashes': hashes,
                             'grading': 'Target/Controls + identical certified public checks + frozen guards for 44 tasks',
                             'exceptions': 'Context checks v2; fixed original product outputs; 6 tasks without frozen guards use public checks only',
                             'original': 'Unmodified pre-evals Agent and seven native tools; common transport and scope/command/budget wrappers; no subagents or fetch',
                             'calls': 'original <=12 rounds, retrieval <=1, full <=2; common 15000-token and 600-second per-arm cap',
                             'public_access': 'same readable public checks and frozen guards available to all; full includes failure feedback, original may invoke both',
                             'order': 'rotate all three policies by task index; fresh independent first answers',
                             'limits': 'Known tasks, not blind; full workflows differ in tools and orchestration; no default integration'}}
    previous.write_json(output / 'manifest.json', manifest)
    for case in cases:
        task = case['task_id']
        cert = certs[task]
        for key in ('before', 'after', 'checks'):
            if digest(snapshot(Path(case[key]))) != case[key + '_hash']:
                raise ValueError('Frozen task changed')
        if (cert['description_hash'] != hashlib.sha256(case['description'].encode()).hexdigest()
                or digest(snapshot(Path(cert['harness']))) != cert['harness_hash']):
            raise ValueError('Public certificate mismatch')
        root = output / 'admission' / task
        root.mkdir(parents=True)
        public, checks = root / 'public', Path(case['checks'])
        shutil.copytree(cert['harness'], public)
        if task == 'click-resource-exception':
            code = (public / 'test_admission.py').read_text(encoding='utf-8')
            (public / 'test_admission.py').write_text(context.extend_checks(code, 'Preserve'), encoding='utf-8')
            checks = root / 'grading'
            shutil.copytree(case['checks'], checks)
            p = checks / 'test_admission.py'
            p.write_text(context.extend_checks(p.read_text(encoding='utf-8'), 'Controls'), encoding='utf-8')
        if task == 'more-gray-partial-repeat':
            product = data['product']
            if digest(snapshot(Path(product['harness']))) != product['harness_hash']:
                raise ValueError('Fixed product checks changed')
            (public / 'test_admission.py').write_bytes((Path(product['harness']) / 'test_admission.py').read_bytes())
        public_outcomes = {label: previous.public_check(case[key], public, case['package'], case['source_root'], root / ('public-' + label))
                           for label, key in [('before', 'before'), ('after', 'after')]}
        private_outcomes = {label: previous.admission.groups(Path(case[key]), checks, case['package'], case['source_root'], root / ('private-' + label))
                            for label, key in [('before', 'before'), ('after', 'after')]}
        if (not previous.certified(public_outcomes) or private_outcomes['before']['Target']['passed']
                or not private_outcomes['before']['Controls']['passed'] or not all(g['passed'] for g in private_outcomes['after'].values())):
            raise ValueError('Unified grader admission failed: ' + task)
        guard = guards.get(task)
        frozen = Path(guard['harness']) if guard else public
        frozen_hash = guard['harness_hash'] if guard else digest(snapshot(public))
        if digest(snapshot(frozen)) != frozen_hash:
            raise ValueError('Frozen guard changed')
        index = previous.baseline.functions.FunctionIndex(Path(case['before']), case['allowed_files'])
        index.refresh()
        observed = previous.retrieval.retrieve(index, case['description'])
        manifest['cases'].append(dict(case, checks=str(checks), checks_hash=digest(snapshot(checks)),
                                     harness=str(public), harness_hash=digest(snapshot(public)),
                                     frozen_harness=str(frozen), frozen_harness_hash=frozen_hash,
                                     evidence=observed['evidence'], description_hash=cert['description_hash'],
                                     public_admission=public_outcomes, private_admission=private_outcomes))
        previous.write_json(output / 'manifest.json', manifest)
        print('admitted', task, flush=True)
    manifest['complete'] = len(manifest['cases']) == 50
    previous.write_json(output / 'manifest.json', manifest)


def intact(manifest):
    for p, h in manifest['protocol']['input_hashes'].items():
        if previous.admission.history.sha(Path(p)) != h:
            raise ValueError('Frozen protocol input changed')
    if digest(snapshot(Path(manifest['upstream']))) != manifest['upstream_hash']:
        raise ValueError('Upstream snapshot changed')
    for case in manifest['cases']:
        for key in ('before', 'after', 'checks', 'harness', 'frozen_harness'):
            if digest(snapshot(Path(case[key]))) != case[key + '_hash']:
                raise ValueError('Task source or checks changed')


def summarize(rows):
    return {p: {'tasks': len(items := [r for r in rows if r['policy'] == p]),
                'passed': sum(r['accepted'] for r in items),
                'controls_passed': sum((r['verification'].get('groups') or {}).get('Controls', {}).get('passed', False) for r in items),
                'tokens': sum((r['worker'].get('metrics') or {}).get('budget_accounted_tokens', 0) for r in items),
                'calls': sum((r['worker'].get('metrics') or {}).get('llm_calls', 0) for r in items),
                'missing_worker_results': sum(r['worker'].get('metrics') is None for r in items),
                'false_completed': [r['task_id'] for r in items if r['worker']['status'] == 'completed' and not r['accepted']],
                'statuses': {s: sum(r['worker']['status'] == s for r in items) for s in sorted({r['worker']['status'] for r in items})},
                'worker_seconds': round(sum(r['process']['seconds'] for r in items), 4)} for p in POLICIES}


def run(output):
    manifest = load(output / 'manifest.json')
    if not manifest['complete'] or (output / 'experiment.json').exists():
        raise ValueError('Require completed manifest and no previous run')
    intact(manifest)
    previous.repair.check_identity(previous.repair.config())
    report = {'complete': False, 'runs': [], 'manifest_sha256': previous.admission.history.sha(output / 'manifest.json'),
              'protocol': manifest['protocol']}

    def save():
        report['summary'] = summarize(report['runs'])
        previous.write_json(output / 'experiment.json', report)

    def unchanged_manifest():
        if previous.admission.history.sha(output / 'manifest.json') != report['manifest_sha256']:
            raise ValueError('Frozen manifest changed')
        intact(manifest)

    save()
    for number, case in enumerate(manifest['cases']):
        order = POLICIES[number % 3:] + POLICIES[:number % 3]
        for policy in order:
            unchanged_manifest()
            root = output / 'runs' / case['task_id'] / policy
            workspace = root / 'workspace'
            shutil.copytree(case['before'], workspace)
            visible = workspace / '.eval-logs' / 'public-tests'
            shutil.copytree(case['harness'], visible)
            visible_frozen = workspace / '.eval-logs' / 'frozen-tests'
            shutil.copytree(case['frozen_harness'], visible_frozen)
            job = {k: case[k] for k in ('description', 'allowed_files', 'package', 'source_root', 'evidence',
                                      'description_hash', 'harness', 'harness_hash', 'frozen_harness', 'frozen_harness_hash')}
            job.update(workspace=str(workspace), original_hash=case['before_hash'], policy=policy,
                       upstream=manifest['upstream'], upstream_hash=manifest['upstream_hash'])
            previous.write_json(root / 'job.json', job)
            process = run_process([sys.executable, '-B', '-m', 'docs.experiments.system_comparison_worker_v1', '--worker', str(root / 'job.json')],
                                  ROOT, 600, root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                                  dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
            result_path = root / 'worker-result.json'
            result = load(result_path) if result_path.exists() and not process['timed_out'] else {
                'status': 'timeout' if process['timed_out'] else 'agent_error', 'metrics': None, 'published': False}
            # Tool/public tests are model-facing material; check they were not edited even though snapshots exclude log folders.
            if (digest(snapshot(visible)) != case['harness_hash']
                    or digest(snapshot(visible_frozen)) != case['frozen_harness_hash']):
                result.update(status='public_check_tampering', published=False)
            unchanged_manifest()
            grade = root / 'verification'
            grade.mkdir()
            verified = previous.baseline.verify(case, workspace, grade)
            public = previous.public_check(workspace, case['harness'], case['package'], case['source_root'], root / 'final-public')
            frozen = previous.public_check(workspace, case['frozen_harness'], case['package'], case['source_root'], root / 'final-frozen')
            accepted = (result['status'] == 'completed' and verified['passed'] and previous.all_pass(public) and previous.all_pass(frozen))
            report['runs'].append({'task_id': case['task_id'], 'split': case['split'], 'policy': policy,
                                   'accepted': accepted, 'worker': result, 'verification': verified,
                                   'public': public, 'frozen': frozen, 'process': process})
            save()
            print(number+1, case['task_id'], policy, result['status'], 'accepted=', accepted, flush=True)
    unchanged_manifest()
    previous.repair.check_identity(previous.repair.config())
    report['complete'] = len(report['runs']) == 150
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        prepare(args.output.resolve())
    else:
        run(args.output.resolve())
