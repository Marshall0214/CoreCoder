"""Re-score all six saved repairs after a documented error-message contract fix."""

import argparse
import json
from pathlib import Path

from docs.experiments import validation_repair_v1 as validation

repair = validation.repair
ROOT = validation.ROOT
SPEC = Path(__file__).with_name('validation-scoring-v2.json')


def run(source, admission, output):
    spec = json.loads(SPEC.read_text(encoding='utf-8'))
    if output.resolve().is_relative_to(source.resolve()):
        raise ValueError('Output must be outside the saved experiment')
    if spec['v1_manifest_sha256'] != validation.MANIFEST_SHA:
        raise ValueError('Scoring specification references another manifest')
    cases, grading, _ = validation.prepare(validation.MANIFEST, admission, output)
    original = json.loads((source / 'experiment.json').read_text(encoding='utf-8'))
    if (repair.audit.sha(source / 'experiment.json') != spec['source_report_sha256']
            or repair.audit.sha(source / 'observations.json') != spec['observations_sha256']
            or not original['complete']
            or len(original['runs']) != 6
            or {(r['task_id'], r['policy']) for r in original['runs']}
            != {(c['task_id'], p) for c in cases for p in repair.POLICIES}):
        raise ValueError('Saved experiment mismatch')
    updated = SPEC.parent / spec['updated_checks']
    if repair.digest(repair.snapshot(updated)) != spec['updated_checks_sha256']:
        raise ValueError('Corrected checks changed')
    output.mkdir(parents=True)
    items = {c['task_id']: (c, g) for c, g in zip(cases, grading)}
    for case, item in items.values():
        checks = updated if case['task_id'] == spec['corrected_task'] else item['checks']
        if repair.digest(repair.snapshot(item['source_root'] / 'after')) != item['after_hash']:
            raise ValueError('Reference source changed')
        for label in ('before', 'after'):
            groups = repair.checked_groups(item['source_root'] / label, checks,
                                           output / 'preflight' / case['task_id'] / label, item['python'], 15)
            valid = (groups['Target']['assertion_failure'] and not groups['Target']['execution_error']
                     and not groups['Target']['passed'] and not groups['Target']['timed_out']
                     and groups['Controls']['passed']) if label == 'before' else all(g['passed'] for g in groups.values())
            if not valid:
                raise ValueError('Corrected admission did not reproduce')
    report = {'protocol': 'validation-rescore-v2', 'post_hoc_scoring_correction': True,
              'new_llm_calls': 0, 'original_llm_calls': 6, 'spec': spec,
              'complete': False, 'runs': []}
    for row in original['runs']:
        case, item = items[row['task_id']]
        root = output / row['task_id'] / row['policy']
        root.mkdir(parents=True)
        saved = source / row['task_id'] / row['policy']
        workspace = saved / 'workspace'
        candidate_hash = repair.digest(repair.snapshot(workspace))
        if candidate_hash != spec['candidate_hashes'][row['task_id'] + '/' + row['policy']]:
            raise ValueError('Saved candidate changed')
        checks = updated if row['task_id'] == spec['corrected_task'] else item['checks']
        verification = repair.verify(item['case'], item['source_root'], checks, workspace,
                                     repair.snapshot(case['before']), case['allowed_files'], root, item['python'], 15)
        if (repair.digest(repair.snapshot(workspace)) != candidate_hash
                or repair.audit.sha(root / 'patch.diff') != repair.audit.sha(saved / 'patch.diff')):
            raise ValueError('Saved patch changed during rescoring')
        accepted = row['worker']['status'] == 'completed' and verification['passed']
        report['runs'].append(dict(row, original_status=row['status'], verification=verification,
                                  accepted=accepted, status='passed' if accepted else
                                  ('failed_verification' if row['worker']['status'] == 'completed' else row['worker']['status'])))
        print(row['task_id'], row['policy'], report['runs'][-1]['status'], flush=True)
    if (repair.audit.sha(source / 'experiment.json') != spec['source_report_sha256']
            or repair.digest(repair.snapshot(updated)) != spec['updated_checks_sha256']):
        raise ValueError('Scoring inputs changed during verification')
    for case, item in items.values():
        if (repair.digest(repair.snapshot(case['before'])) != case['before_hash']
                or repair.digest(repair.snapshot(item['source_root'] / 'after')) != item['after_hash']
                or repair.digest(repair.snapshot(item['checks'])) != item['case']['checks_hash']):
            raise ValueError('Admitted inputs changed during rescoring')
    report['complete'] = True
    report['summary'] = repair.summarize(report['runs'])
    (output / 'experiment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / '.tmp/real-defects/validation-repair-v1')
    parser.add_argument('--admission', type=Path, default=ROOT / '.tmp/real-defects/validation-admission-v1-final/admission.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.source.resolve(), args.admission.resolve(), args.output.resolve())
