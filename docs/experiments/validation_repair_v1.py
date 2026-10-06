"""Frozen-strategy line/function repair comparison on three post-design tasks."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import function_index_audit_v1 as retrieval
from docs.experiments import function_index_repair_v1 as repair
from evals.schema import relative_path

ROOT = repair.audit.ROOT
MANIFEST = Path(__file__).with_name('validation-suite-v1.json')
MANIFEST_SHA = '3dbed44448ed8af27f27f1a8f9569efba1af0343c2b237d3d7901cfadbf0dc8a'


def prepare(manifest_path, admission_path, output):
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
            or repair.audit.sha(Path(retrieval.__file__)) != manifest['retrieval_adapter_sha256']
            or repair.audit.sha(Path(repair.__file__)) != manifest['repair_adapter_sha256']):
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
        allowed = sorted(p for p in repair.snapshot(before) if p.startswith('src/click/') and p.endswith('.py'))
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


def observe_all(cases, output):
    observations = []
    for case in cases:
        observed = retrieval.observe(case, {'query': case['description'] + ' contract contracts'})
        observed['policies'] = {p: observed['policies'][p] for p in repair.POLICIES}
        for policy in observed['policies'].values():
            repair.validate_evidence(case['before'], case['allowed_files'], policy['evidence'])
        observations.append(observed)
    path = output / 'observations.json'
    path.write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding='utf-8')
    return observations


def run(manifest_path, admission_path, output):
    cases, grading, manifest = prepare(manifest_path, admission_path, output)
    repair.check_identity(repair.config())
    output.mkdir(parents=True)
    observations = observe_all(cases, output)
    protocol = {'protocol': 'post-design-validation-repair-v1', 'expected_runs': 6,
                'unique_tasks': 3, 'within_repository_validation': True, 'benchmark_eligible': False,
                'manifest_sha256': MANIFEST_SHA, 'observations_sha256': repair.audit.sha(output / 'observations.json'),
                'engine_hash': manifest['engine_hash'], 'config': repair.config().to_dict(),
                'repair_model_digest': repair.MODEL_DIGEST, 'llm_calls_per_branch': 1, 'tools': [],
                'dependency_depth': 0, 'all_candidates_retained': True,
                'order': [{'task_id': c['task_id'], 'policies': list(repair.POLICIES if i % 2 == 0 else repair.POLICIES[::-1])}
                          for i, c in enumerate(cases)],
                'adapter_hashes': {p.relative_to(ROOT).as_posix(): repair.audit.sha(p) for p in
                                   (Path(__file__), Path(retrieval.__file__), Path(repair.__file__), Path(repair.patcher.__file__))}}
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    # Selection for ALL tasks is on disk before opening after snapshots or scoring tests.
    for case, item in zip(cases, grading):
        if repair.digest(repair.snapshot(item['source_root'] / 'after')) != item['after_hash']:
            raise ValueError('Reference snapshot changed')
        for label in ('before', 'after'):
            groups = repair.checked_groups(item['source_root'] / label, item['checks'],
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
            verification = repair.verify(item['case'], item['source_root'], item['checks'], workspace, before,
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--admission', type=Path, default=ROOT / '.tmp/real-defects/validation-admission-v1-final/admission.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.manifest.resolve(), args.admission.resolve(), args.output.resolve())


if __name__ == '__main__':
    main()
