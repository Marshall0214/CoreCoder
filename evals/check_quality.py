"""Read-only, post-hoc check diagnostics; never supplies feedback to a model."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def observed_pass(outcome):
    if (not isinstance(outcome, dict) or outcome.get('timed_out') is not False
            or outcome.get('checks_unchanged') is not True
            or type(outcome.get('tests_run')) is not int or outcome['tests_run'] < 1
            or type(outcome.get('passed')) is not bool):
        return None
    # Infrastructure/import errors are not evidence of defect detection.
    if outcome['passed'] is False and outcome.get('assertion_failure') is not True:
        return None
    if type(outcome.get('returncode')) is not int or (outcome['returncode'] == 0) != outcome['passed']:
        return None
    return outcome['passed']


def diagnose(report):
    checks = report.get('worker', {}).get('public_checks', {})
    original = observed_pass(checks.get('original'))
    # A failed final execution must not fall back to a successful initial candidate.
    final = observed_pass(checks['final'] if 'final' in checks else checks.get('candidate'))
    accepted = report.get('accepted') is True
    return {'run_id': report['run_id'], 'task_id': report['task_id'],
            'protocol': report.get('evaluation_protocol'), 'fixture_hash': report.get('fixture_hash'),
            'source_hash': report.get('implementation', {}).get('source_hash'),
            'generation_status': checks.get('generation_status'),
            'review_status': checks.get('review_status'),
            'retained_tests': len(checks.get('accepted_tests', [])),
            'original_pass': original, 'final_public_pass': final, 'independently_accepted': accepted,
            'defect_detection': 'detected' if original is False else 'missed' if original is True else 'unknown',
            'accepted_patch_conflict': accepted and final is False,
            'conflict_interpretation': 'requires_contract_review' if accepted and final is False else None,
            'contract_ambiguity': 'not_automatically_determined',
            'feedback_attempts': report.get('worker', {}).get('feedback_attempts', 0)}


def collect(root):
    rows, seen = [], {}
    for path in sorted(root.rglob('report.json')):
        raw = path.read_bytes()
        report = json.loads(raw)
        if not isinstance(report, dict) or not isinstance(report.get('run_id'), str) or not report.get('task_id'):
            raise ValueError(f'Invalid run report: {path}')
        fingerprint = hashlib.sha256(raw).hexdigest()
        if report['run_id'] in seen:
            if seen[report['run_id']] != fingerprint:
                raise ValueError(f'Conflicting duplicate run: {report["run_id"]}')
            continue
        seen[report['run_id']] = fingerprint
        if not report.get('worker', {}).get('public_checks'):
            continue
        rows.append(diagnose(report) | {'report_path': path.resolve().as_posix(), 'report_hash': fingerprint})
    if not rows:
        raise ValueError('No public-check run reports found')
    groups = {}
    for row in rows:
        key = (row['protocol'], row['fixture_hash'], row['source_hash'])
        groups.setdefault(key, []).append(row)
    return {'scope': 'post-hoc diagnostics only; no test selection or model feedback', 'runs': rows,
            'groups': [{'protocol': key[0], 'fixture_hash': key[1], 'source_hash': key[2],
                        'runs': len(items), 'defect_detection': dict(Counter(r['defect_detection'] for r in items)),
                        'accepted_patch_conflicts': sum(r['accepted_patch_conflict'] for r in items)}
                       for key, items in groups.items()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New diagnostic directory')
    args = parser.parse_args()
    result = collect(args.input)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'quality.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Public-check quality diagnostics', '', result['scope'], '',
             '| Task | Run | Original defect | Final checks | Accepted patch conflict |',
             '| --- | --- | --- | --- | --- |']
    for row in result['runs']:
        lines.append(f"| {row['task_id']} | {row['run_id']} | {row['defect_detection']} | "
                     f"{row['final_public_pass']} | {row['accepted_patch_conflict']} |")
    lines += ['', 'A conflict does not prove that the checks are wrong or that the patch is correct.',
              'Contract ambiguity requires manual public-contract review. Unknown executions are not failures.', '']
    (args.output / 'quality.md').write_text('\n'.join(lines), encoding='utf-8')
    print(args.output.resolve() / 'quality.md')


if __name__ == '__main__':
    main()
