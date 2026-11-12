"""Read saved historical/current feedback receipts, no tests or inference."""
import collections
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_arm(batch, arm):
    report = read(batch / 'report.json')
    rows = report['tasks'][arm]
    status_counts = collections.Counter()
    patch_errors = collections.Counter()
    records, missing = [], []
    expected_labels = ('base1',) if arm == 'no_harness' else ('base1', 'inv1', 'dom1', 'agg1')
    for task, top in rows.items():
        task_root = batch / 'arms' / arm / task
        folders = {p.parent.parent.name: p.parent.parent for p in task_root.glob(f'executions/*/{task}/*/feedback/report.json')}
        for label in expected_labels:
            if label not in folders:
                missing.append({'task': task, 'label': label, 'outer_status': top.get('status')})
                continue
            folder = folders[label]
            feedback = read(folder / 'feedback/report.json')
            errors = collections.Counter(r.get('patch_error', {}).get('code') for r in feedback.get('rounds', []) if r.get('patch_error'))
            patch_errors.update(errors)
            status_counts[feedback['status']] += 1
            invalids = []
            receipt_paths = [folder / 'feedback/validation-000/report.json', *sorted(folder.glob('feedback/rounds/*/validation/report.json'))]
            for receipt_path in receipt_paths:
                if not receipt_path.exists():
                    continue
                receipt = read(receipt_path)
                if receipt.get('status') != 'blocked':
                    continue
                logs = []
                for log in receipt_path.parent.glob('public-logs/*stderr.txt'):
                    text = log.read_text(encoding='utf-8', errors='replace')
                    logs.append({'path': str(log), 'sha256': digest(log), 'text': text,
                                 'runner_py_io_error': '/runner.py' in text and 'Input/output error' in text,
                                 'literal_invalid_schema': 'invalid_schema' in text})
                invalids.append({'path': str(receipt_path), 'sha256': digest(receipt_path),
                                 'status': receipt['status'], 'infrastructure_error': receipt.get('infrastructure_error'),
                                 'stderr_files': logs, 'stderr_unavailable': not bool(logs)})
            records.append({'task': task, 'label': label, 'folder': str(folder),
                            'feedback_report_sha256': digest(folder / 'feedback/report.json'),
                            'status': feedback['status'], 'accepted': feedback['accepted'],
                            'attempts': feedback['feedback_rounds_attempted'],
                            'applied_patches': feedback.get('applied_patches'), 'patch_errors': dict(errors),
                            'changed_files': feedback.get('changed_files'),
                            'outer_delivered_resolved': top.get('resolved'),
                            'is_delivered': str(folder) == top.get('result', {}).get('final_rollout'),
                            'blocked_validation_receipts': invalids})
    blocked = [b for row in records for b in row['blocked_validation_receipts']]
    return {'batch': str(batch), 'arm': arm, 'expected_tasks': len(rows),
            'expected_feedback_folders': len(rows) * len(expected_labels),
            'available_feedback_reports': len(records), 'missing': missing,
            'status_counts': dict(status_counts), 'feedback_attempts': sum(r['attempts'] for r in records),
            'applied_patches': sum(r['applied_patches'] or 0 for r in records),
            'patch_error_counts': dict(patch_errors),
            'blocked_validation_receipts': len(blocked),
            'blocked_with_runner_py_io_stderr': sum(any(s['runner_py_io_error'] for s in b['stderr_files']) for b in blocked),
            'blocked_stderr_unavailable': sum(b['stderr_unavailable'] for b in blocked),
            'blocked_with_literal_invalid_schema': sum(any(s['literal_invalid_schema'] for s in b['stderr_files']) for b in blocked),
            'records': records}


if __name__ == '__main__':
    old = ROOT / '.tmp/harness2-vs-control-50-20261105'
    new = ROOT / '.tmp/harness2-v2-50-20261106'
    data = {'schema': 'historical-feedback-audit-v1', 'model_calls': 0, 'tests_run': 0,
            'scope': 'Saved artifacts only. Missing feedback reports remain unknown, never counted as successful execution.',
            'arms': {'historical_control': audit_arm(old, 'no_harness'),
                     'historical_harness': audit_arm(old, 'harness2'),
                     'current_harness': audit_arm(new, 'harness2')}}
    (OUT / 'historical-feedback-audit.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: {a: b for a, b in v.items() if a != 'records'} for k, v in data['arms'].items()}, ensure_ascii=False, indent=2))
