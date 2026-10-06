"""Frozen line/function comparison on three admitted ItsDangerous tasks."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import second_repo_admission_v1 as admission
from docs.experiments import validation_repair_v1 as validation
from evals.runner import changes
from evals.schema import relative_path

repair = validation.repair
retrieval = validation.retrieval
ROOT = validation.ROOT
MANIFEST = Path(__file__).with_name('second-repo-suite-v1.json')
MANIFEST_SHA = '190edb5b580b12380041c2e2916aef5b0ed198fbe80d9341ebda5b011da89ce4'
observe_all = validation.observe_all


def verify(case, source_root, checks, workspace, original, allowed, root, python, timeout=15):
    candidate = repair.snapshot(workspace)
    changed, patch = changes(original, candidate)
    (root / 'patch.diff').write_text(patch, encoding='utf-8')
    violations = sorted(set(changed) - set(allowed))
    violations += [name for name in allowed if name not in candidate or (workspace / name).is_symlink()]
    if violations:
        return {'passed': False, 'changed_files': changed, 'scope_violations': sorted(set(violations)),
                'target': None, 'regression': None}
    grading = root / 'grading'
    shutil.copytree(source_root / 'before', grading)
    for name in allowed:
        (grading / name).write_bytes(candidate[name])
    groups = admission.checked_groups(grading, checks, root / 'grading-logs', python, timeout)
    return {'passed': all(g['passed'] for g in groups.values()), 'changed_files': changed,
            'scope_violations': [], 'target': groups['Target'], 'regression': groups['Controls'],
            'regression_scope': 'public Controls only; not full upstream tests'}


def prepare(manifest_path, admission_path, output):
    if (repair.audit.sha(Path(retrieval.__file__)) != 'abba3339be8838c68693aad344fc106b44e36201d0db1cffdc44f6a6637630a7'
            or repair.audit.sha(Path(repair.__file__)) != '97d6d3af30723894b49ee0ff340ba8bb34b25b18839d728e6c7546df0d9d0aac'):
        raise ValueError('Frozen retrieval or repair strategy changed')
    if repair.audit.sha(manifest_path) != MANIFEST_SHA:
        raise ValueError('Validation manifest changed')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    directory = manifest_path.parent
    public_path = directory / relative_path(manifest['public_tasks'])
    catalog_path = directory / relative_path(manifest['catalog'])
    checks_root = directory / relative_path(manifest['checks_root'])
    if (repair.audit.sha(public_path) != manifest['public_tasks_sha256']
            or repair.audit.sha(catalog_path) != manifest['catalog_sha256']
            or repair.digest(repair.snapshot(checks_root)) != manifest['checks_sha256']
            or repair.audit.sha(admission_path) != manifest['recorded_admission_sha256']
            or repair.audit.sha(Path(admission.__file__)) != manifest['adapter_sha256']):
        raise ValueError('Frozen validation inputs or strategy changed')
    report = json.loads(admission_path.read_text(encoding='utf-8'))
    public = json.loads(public_path.read_text(encoding='utf-8'))['tasks']
    ids = [r['task_id'] for r in manifest['cases']]
    if (len(ids) != 3 or len(set(ids)) != 3 or ids != [r['task_id'] for r in public]
            or ids != [r['case_id'] for r in report['cases']] or not report['complete']
            or report['catalog_hash'] != manifest['catalog_sha256']):
        raise ValueError('Validation pool or admission mismatch')
    cases, grading = [], []
    for task, pinned, admitted in zip(public, manifest['cases'], report['cases']):
        name = relative_path(task['task_id'])
        source_root = admission_path.parent / name
        before = source_root / 'before'
        allowed = sorted(p for p in repair.snapshot(before) if p.startswith('src/itsdangerous/') and p.endswith('.py'))
        if (set(task) != {'task_id', 'repo', 'before_commit', 'description', 'allowed_files'}
                or allowed != task['allowed_files'] or task['before_commit'] != pinned['before_commit']
                or not admitted['admitted'] or admitted['before_commit'] != pinned['before_commit']
                or admitted['after_commit'] != pinned['after_commit']
                or repair.digest(repair.snapshot(before)) != pinned['before_tree_hash']
                or repair.digest(repair.snapshot(checks_root / name)) != pinned['checks_hash']):
            raise ValueError('Public projection or admitted source changed')
        cases.append({'task_id': name, 'before': before, 'before_hash': pinned['before_tree_hash'],
                      'description': task['description'], 'allowed_files': allowed})
        grading.append({'case': admitted, 'source_root': source_root, 'checks': checks_root / name,
                        'after_hash': pinned['after_tree_hash'], 'python': Path(report['test_environment']['executable'])})
    if output.exists() or any(output.resolve().is_relative_to(r['source_root'].resolve()) for r in grading) or output.resolve().is_relative_to(checks_root.resolve()):
        raise ValueError('Use fresh output outside admitted sources and checks')
    return cases, grading, manifest


def run(manifest_path, admission_path, output):
    cases, grading, manifest = prepare(manifest_path, admission_path, output)
    repair.check_identity(repair.config())
    output.mkdir(parents=True)
    observations = observe_all(cases, output)
    protocol = {'protocol': 'second-repository-repair-v1', 'expected_runs': 6,
                'unique_tasks': 3, 'repository': 'pallets/itsdangerous', 'previously_inspected_tasks': True, 'benchmark_eligible': False,
                'manifest_sha256': MANIFEST_SHA, 'observations_sha256': repair.audit.sha(output / 'observations.json'),
                'engine_hash': manifest['engine_hash'], 'config': repair.config().to_dict(),
                'repair_model_digest': repair.MODEL_DIGEST, 'llm_calls_per_branch': 1, 'tools': [],
                'dependency_depth': 0, 'all_candidates_retained': True,
                'order': [{'task_id': c['task_id'], 'policies': list(repair.POLICIES if i % 2 == 0 else repair.POLICIES[::-1])}
                          for i, c in enumerate(cases)],
                'adapter_hashes': {p.relative_to(ROOT).as_posix(): repair.audit.sha(p) for p in
                                   (Path(__file__), Path(retrieval.__file__), Path(repair.__file__), Path(repair.patcher.__file__), Path(admission.__file__))}}
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    # Selection for ALL tasks is on disk before opening after snapshots or scoring tests.
    for case, item in zip(cases, grading):
        if repair.digest(repair.snapshot(item['source_root'] / 'after')) != item['after_hash']:
            raise ValueError('Reference snapshot changed')
        for label in ('before', 'after'):
            groups = admission.checked_groups(item['source_root'] / label, item['checks'],
                                           output / 'preflight' / case['task_id'] / label, item['python'], 15)
            valid = (groups['Target']['assertion_failure'] and not groups['Target']['execution_error']
                     and not groups['Target']['passed'] and not groups['Target']['timed_out']
                     and groups['Controls']['passed']) if label == 'before' else all(g['passed'] for g in groups.values())
            if not valid:
                raise ValueError('Frozen admission behavior no longer reproduces')
    report = {'protocol': protocol, 'complete': False, 'runs': []}

    def save():
        report['summary'] = repair.summarize(report['runs'])
        (output / 'experiment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    save()
    for case, item, observed, block in zip(cases, grading, observations, protocol['order']):
        for policy in block['policies']:
            repair.check_identity(repair.config())
            if (repair.audit.sha(manifest_path) != MANIFEST_SHA
                    or repair.audit.sha(output / 'observations.json') != protocol['observations_sha256']
                    or any(repair.audit.sha(ROOT / name) != expected for name, expected in protocol['adapter_hashes'].items())):
                raise ValueError('Frozen protocol or evidence changed')
            root = output / case['task_id'] / policy
            root.mkdir(parents=True)
            workspace = root / 'workspace'
            shutil.copytree(case['before'], workspace)
            before = repair.snapshot(workspace)
            if repair.digest(before) != case['before_hash']:
                raise ValueError('Before source changed')
            evidence = observed['policies'][policy]['evidence']
            repair.validate_evidence(workspace, case['allowed_files'], evidence)
            job_path = root / 'job.json'
            job_path.write_text(json.dumps({'workspace': str(workspace.resolve()), 'description': case['description'],
                                            'allowed_files': case['allowed_files'], 'evidence': evidence}, ensure_ascii=False), encoding='utf-8')
            env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
            process = repair.run_process([sys.executable, '-m', 'docs.experiments.retrieved_function_repair_v1', '--worker', str(job_path.resolve())],
                                         workspace, 600, root / 'worker.stdout.txt', root / 'worker.stderr.txt', env)
            path = root / 'worker-result.json'
            result = (json.loads(path.read_text(encoding='utf-8')) if path.exists() and process['returncode'] == 0 and not process['timed_out']
                      else {'status': 'timeout' if process['timed_out'] else 'agent_error', 'metrics': None})
            verification = verify(item['case'], item['source_root'], item['checks'], workspace, before,
                                         case['allowed_files'], root, item['python'], 15)
            accepted = result['status'] == 'completed' and verification['passed']
            report['runs'].append({'task_id': case['task_id'], 'policy': policy, 'worker': result,
                                  'verification': verification, 'accepted': accepted,
                                  'status': 'passed' if accepted else ('failed_verification' if result['status'] == 'completed' else result['status']),
                                  'evidence_chars': sum(len(r['content']) for r in evidence), 'process': process})
            save()
            print(f"{case['task_id']} {policy}: {report['runs'][-1]['status']}", flush=True)
    repair.check_identity(repair.config())
    for case, item in zip(cases, grading):
        if (repair.digest(repair.snapshot(case['before'])) != case['before_hash']
                or repair.digest(repair.snapshot(item['source_root'] / 'after')) != item['after_hash']
                or repair.digest(repair.snapshot(item['checks'])) != item['case']['checks_hash']):
            raise ValueError('Admitted sources or checks changed during repairs')
    report['complete'] = len(report['runs']) == 6
    save()
    print(json.dumps(report['summary'], indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', type=Path, default=ROOT / '.tmp/real-defects/second-repo-admission-v1-final/admission.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(MANIFEST, args.admission.resolve(), args.output.resolve())
