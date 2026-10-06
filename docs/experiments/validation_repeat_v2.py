"""Three new repeats using frozen corrected scoring and original retrieval evidence."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import repeat_function_index_repair_v1 as repeat
from docs.experiments import validation_repair_v1 as validation

repair = validation.repair
retrieval = validation.retrieval
ROOT = validation.ROOT
MANIFEST_SHA = validation.MANIFEST_SHA
prepare = validation.prepare
observe_all = validation.observe_all
SPEC = Path(__file__).with_name('validation-prospective-v2.json')
SPEC_SHA = '6fffda44dac19694af1776a2a82f48330aebcc609122fff84d86ea18f7105b92'


def run(admission_path, output):
    manifest_path = validation.MANIFEST
    cases, grading, manifest = prepare(manifest_path, admission_path, output)
    if repair.audit.sha(SPEC) != SPEC_SHA:
        raise ValueError('Prospective scoring specification changed')
    spec = json.loads(SPEC.read_text(encoding='utf-8'))
    if spec['v1_manifest_sha256'] != validation.MANIFEST_SHA or spec['config'] != repair.config().to_dict():
        raise ValueError('Frozen scoring or configuration changed')
    corrected = SPEC.parent / spec['updated_checks']
    if output.resolve().is_relative_to(corrected.resolve()):
        raise ValueError('Output must be outside scoring checks')
    if repair.digest(repair.snapshot(corrected)) != spec['updated_checks_sha256']:
        raise ValueError('Corrected checks changed')
    for case, item in zip(cases, grading):
        if case['task_id'] == spec['corrected_task']:
            item['checks'] = corrected
            item['case'] = dict(item['case'], checks_hash=spec['updated_checks_sha256'])
    repair.check_identity(repair.config())
    output.mkdir(parents=True)
    observations = observe_all(cases, output)
    if repair.audit.sha(output / 'observations.json') != spec['observations_sha256']:
        raise ValueError('Evidence differs from original comparison')
    protocol = {'protocol': 'validation-prospective-repeat-v2', 'expected_runs': 18,
                'repeats': 3, 'prior_runs_included': False, 'scoring_sha256': SPEC_SHA,
                'prospective_scoring': True, 'previously_inspected_tasks': True,
                'unique_tasks': 3, 'within_repository_validation': True, 'benchmark_eligible': False,
                'manifest_sha256': MANIFEST_SHA, 'observations_sha256': repair.audit.sha(output / 'observations.json'),
                'engine_hash': manifest['engine_hash'], 'config': repair.config().to_dict(),
                'repair_model_digest': repair.MODEL_DIGEST, 'llm_calls_per_branch': 1, 'tools': [],
                'dependency_depth': 0, 'all_candidates_retained': True,
                'order': [{'task_id': c['task_id'], 'policies': list(repair.POLICIES if i % 2 == 0 else repair.POLICIES[::-1])}
                          for i, c in enumerate(cases)],
                'adapter_hashes': {p.relative_to(ROOT).as_posix(): repair.audit.sha(p) for p in
                                   (Path(__file__), Path(retrieval.__file__), Path(repair.__file__), Path(repair.patcher.__file__), Path(repeat.__file__), Path(validation.__file__))}}
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
        report.update(repeat.aggregate(report['runs'], [c['task_id'] for c in cases], 3))
        (output / 'experiment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    save()
    for number in range(1, 4):
        print(f'Repeat {number}/3', flush=True)
        for case, item, observed, block in zip(cases, grading, observations, protocol['order']):
            order = block['policies'] if number % 2 else block['policies'][::-1]
            for policy in order:
                repair.check_identity(repair.config())
                if (repair.audit.sha(SPEC) != SPEC_SHA
                        or repair.digest(repair.snapshot(corrected)) != spec['updated_checks_sha256']
                        or repair.audit.sha(manifest_path) != MANIFEST_SHA
                        or repair.audit.sha(output / 'observations.json') != protocol['observations_sha256']
                        or any(repair.audit.sha(ROOT / name) != expected for name, expected in protocol['adapter_hashes'].items())):
                    raise ValueError('Frozen protocol or evidence changed')
                root = output / f'repeat-{number:02d}' / case['task_id'] / policy
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
                report['runs'].append({'repeat': number, 'task_id': case['task_id'], 'policy': policy, 'worker': result,
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
    report['complete'] = len(report['runs']) == 18
    save()
    print(json.dumps(report['summary'], indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', type=Path, default=ROOT / '.tmp/real-defects/validation-admission-v1-final/admission.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.admission.resolve(), args.output.resolve())
