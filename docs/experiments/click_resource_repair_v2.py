"""Versioned Context-stack checks, offline admission, then one bounded live repair."""
import argparse
import ast
import copy
import json
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import click_context_controls_v1 as stack
from docs.experiments import frozen_feedback_v1 as guarded
from evals.process import run_process
from evals.runner import digest, snapshot

previous = guarded.previous
TASK = 'click-resource-exception'


def extend_checks(code, group):
    """Add regression methods to the selected group; preserve every original test."""
    tree = ast.parse(code)
    targets = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == group]
    if len(targets) != 1:
        raise ValueError('Require unique check group: ' + group)
    additions = next(n for n in ast.parse(stack.CODE).body if isinstance(n, ast.ClassDef)).body
    names = {n.name for n in targets[0].body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if any(n.name in names for n in additions):
        raise ValueError('Regression method collides with existing check')
    targets[0].body.extend(copy.deepcopy(additions))
    source = ast.unparse(ast.fix_missing_locations(tree)) + '\n'
    compile(source, '<context-checks-v2>', 'exec')
    return source


def admitted(public, private, bad_public, bad_private):
    return (previous.certified(public)
            and not private['before']['Target']['passed'] and private['before']['Controls']['passed']
            and all(g['passed'] for g in private['reference'].values())
            and all(v['Preserve']['tests_run'] == 4 and v['Reproduce']['tests_run'] == 1 for v in public.values())
            and all(v['Controls']['tests_run'] == 4 and v['Target']['tests_run'] == 2 for v in private.values())
            and bad_private['Target']['passed'] and not bad_private['Controls']['passed']
            and bad_private['Controls']['tests_run'] == 4 and not bad_private['Controls']['timed_out']
            and bad_private['Controls']['failures'] > 0
            and not bad_public['Preserve']['passed'] and bad_public['Preserve']['tests_run'] == 4
            and not bad_public['Preserve']['timed_out'] and bad_public['Preserve']['failures'] > 0)


def run(args):
    load = stack.comparison.replay.load
    admission = load(args.admission)
    certs, frozen = load(args.certificates), load(args.frozen_audit)
    history, context = load(args.comparison), load(args.context_audit)
    if not all(r['complete'] for r in (admission, certs, frozen, history, context)) or not context['certified']:
        raise ValueError('Require complete frozen inputs and certified context audit')
    if (certs['admission_hash'] != previous.admission.history.sha(args.admission)
            or context['experiment_sha256'] != previous.admission.history.sha(args.comparison)):
        raise ValueError('Input provenance mismatch')
    case = next(c for c in admission['cases'] if c['task_id'] == TASK)
    cert = next(c for c in certs['cases'] if c['task_id'] == TASK)
    guard = next(c for c in frozen['cases'] if c['task_id'] == TASK)
    if not cert['certified'] or not guard['certified'] or case['split'] != 'development':
        raise ValueError('Task must be certified development case')
    historical_job = load(args.comparison.parent / TASK / 'jobs.json')['frozen-feedback']
    bad = args.comparison.parent / TASK / 'frozen-feedback' / 'workspace'
    protected = [Path(case[k]).resolve() for k in ('before', 'after', 'checks')]
    protected += [Path(cert['harness']).resolve(), Path(guard['harness']).resolve(), args.comparison.parent.resolve()]
    output = args.output.resolve()
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('Fresh output outside frozen inputs required')
    files = [args.admission, args.certificates, args.frozen_audit, args.comparison, args.context_audit,
             Path(__file__), Path(stack.__file__), Path(guarded.__file__), Path(previous.__file__)]
    hashes = {str(p.resolve()): previous.admission.history.sha(p) for p in files}

    def unchanged():
        if any(previous.admission.history.sha(Path(p)) != h for p, h in hashes.items()):
            raise ValueError('Frozen input changed')
        for key in ('before', 'after', 'checks'):
            if digest(snapshot(Path(case[key]))) != case[key + '_hash']:
                raise ValueError('Source or independent checks changed')
        for value in (cert, guard):
            if digest(snapshot(Path(value['harness']))) != value['harness_hash']:
                raise ValueError('Historical public harness changed')
        if digest(snapshot(bad)) != context['source_hashes']['frozen-feedback']:
            raise ValueError('Known regression candidate changed')

    unchanged()
    output.mkdir(parents=True)
    public_path, private_path = output / 'public-checks-v2', output / 'grading-checks-v2'
    public_path.mkdir()
    (public_path / 'test_admission.py').write_text(
        extend_checks((Path(cert['harness']) / 'test_admission.py').read_text(encoding='utf-8'), 'Preserve'), encoding='utf-8')
    shutil.copytree(case['checks'], private_path)
    grading_file = private_path / 'test_admission.py'
    grading_file.write_text(extend_checks(grading_file.read_text(encoding='utf-8'), 'Controls'), encoding='utf-8')
    public_hash, private_hash = digest(snapshot(public_path)), digest(snapshot(private_path))
    public = {label: previous.public_check(case[label], public_path, case['package'], case['source_root'],
                                         output / ('public-' + label)) for label in ('before', 'after')}
    private = {label: previous.admission.groups(Path(case[key]), private_path, case['package'], case['source_root'],
                                                output / ('grading-' + label))
               for label, key in [('before', 'before'), ('reference', 'after')]}
    bad_public = previous.public_check(bad, public_path, case['package'], case['source_root'], output / 'public-known-regression')
    bad_private = previous.admission.groups(bad, private_path, case['package'], case['source_root'], output / 'grading-known-regression')
    certificate = {'task_id': TASK, 'version': 'context-stack-v2',
                   'certified': admitted(public, private, bad_public, bad_private),
                   'public': public, 'independent': private, 'known_regression_public': bad_public,
                   'known_regression_independent': bad_private, 'public_hash': public_hash, 'private_hash': private_hash,
                   'input_hashes': hashes, 'model_calls': 0,
                   'provenance': 'Three stack preservation scenarios from post-hoc audit; original and reference both pass; no reference-generated expectations'}
    previous.write_json(output / 'certificate.json', certificate)
    if not certificate['certified']:
        raise ValueError('New protocol admission failed; no inference allowed')
    unchanged()
    live = output / 'live'
    workspace = live / 'workspace'
    shutil.copytree(case['before'], workspace)
    job = {k: case[k] for k in ('description', 'allowed_files', 'package', 'source_root')}
    job.update(workspace=str(workspace), evidence=historical_job['evidence'], original_hash=case['before_hash'],
               description_hash=cert['description_hash'], harness=str(public_path), harness_hash=public_hash,
               frozen_harness=guard['harness'], frozen_harness_hash=guard['harness_hash'])
    previous.write_json(live / 'job.json', job)
    process = run_process([sys.executable, '-B', '-m', 'docs.experiments.frozen_feedback_v1', '--worker', str(live / 'job.json')],
                          previous.ROOT, 600, live / 'worker.stdout.txt', live / 'worker.stderr.txt',
                          dict(os.environ, PYTHONPATH=str(previous.ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
    if process['timed_out'] or process['returncode'] != 0:
        raise RuntimeError('Live worker failed; inspect preserved logs')
    unchanged()
    if (digest(snapshot(public_path)), digest(snapshot(private_path))) != (public_hash, private_hash):
        raise ValueError('Versioned checks changed')
    result = load(live / 'worker-result.json')
    grading_case = dict(case, checks=str(private_path), checks_hash=private_hash)
    grade = output / 'verification'
    grade.mkdir()
    verified = previous.baseline.verify(grading_case, workspace, grade)
    accepted = result['status'] == 'completed' and result.get('published', False) and verified['passed']
    unchanged()
    report = {'complete': True, 'task_id': TASK, 'accepted': accepted, 'certificate': certificate,
              'worker': result, 'verification': verified, 'process': process,
              'protocol': {'config': previous.repair.config().to_dict(), 'model_digest': previous.repair.MODEL_DIGEST,
                           'source': 'fresh original-source repair; at most one public correction; not repair of reference code',
                           'private_in_worker': False, 'default_agent_api_changed': False,
                           'limits': 'One known development task; new Controls share public regression scenarios, independently executed; not blind or full upstream suite'},
              'decision': 'known_regression_repaired_under_v2_checks' if accepted else 'stop_candidate_not_accepted'}
    previous.write_json(output / 'repair.json', report)
    print(json.dumps({'accepted': accepted, 'status': result['status'], 'metrics': result.get('metrics'),
                      'target': verified['groups']['Target']['passed'], 'controls': verified['groups']['Controls']['passed']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('admission', 'certificates', 'frozen-audit', 'comparison', 'context-audit', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    run(parser.parse_args())
