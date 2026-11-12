"""Read-only receipts audit. Runs no inference, project code, tests or selectors."""
import collections
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BATCH = ROOT / '.tmp/harness2-v2-50-20261106'
OUT = Path(__file__).resolve().parent
PRIORITY = ('agg1', 'base1', 'inv1', 'dom1')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def final_validation(folder):
    report = read(folder / 'report.json')
    matches = []
    for receipt in [folder / 'validation-000/report.json', *sorted(folder.glob('rounds/*/validation/report.json'))]:
        if receipt.exists():
            data = read(receipt)
            if data.get('candidate_hash') == report['final_candidate_hash']:
                matches.append({'path': str(receipt), 'status': data.get('status'),
                                'accepted': data.get('accepted'), 'reasons': data.get('reasons'),
                                'infrastructure_error': data.get('infrastructure_error'),
                                'sha256': sha(receipt)})
    return matches


def audit():
    report = read(BATCH / 'report.json')
    old = read(BATCH / 'historical/report.json')
    counts = collections.Counter()
    label_counts = {label: collections.Counter() for label in PRIORITY}
    tasks = {}
    for task, row in report['tasks']['harness2'].items():
        selection_path = BATCH / 'arms/harness2' / task / 'candidate-selection.json'
        selection = read(selection_path)
        chosen = selection['chosen_label']
        expected = next((label for label in PRIORITY if selection['candidates'].get(label, {}).get('public_accepted')), None)
        if expected is None and not selection['candidates'][selection['official_label']].get('integrity_error'):
            expected = selection['official_label']
        assert expected == chosen == row['result']['adopted_label']
        assert selection['independent_grading_used'] is False and selection['model_calls'] == 0
        chosen_public = selection['candidates'][chosen]['public_accepted']
        counts[f'chosen_{chosen}'] += 1
        counts[f'public_{str(chosen_public).lower()}_independent_{str(row["resolved"]).lower()}'] += 1
        candidates = {}
        for label, candidate in selection['candidates'].items():
            folder = Path(candidate['folder'])
            feedback = read(folder / 'feedback/report.json')
            initial = read(folder / 'feedback/validation-000/report.json')
            final_hash = feedback['final_candidate_hash']
            label_counts[label]['public_accepted'] += candidate['public_accepted']
            label_counts[label][f'feedback_{feedback["status"]}'] += 1
            independent_scope = 'graded chosen candidate' if label == chosen else 'not independently graded'
            if label != chosen and final_hash == read(Path(selection['chosen_folder']) / 'feedback/report.json')['final_candidate_hash']:
                independent_scope = 'same final workspace hash as graded chosen candidate; no separate grade'
            error_counts = collections.Counter(r.get('patch_error', {}).get('code') for r in feedback['rounds'] if r.get('patch_error'))
            candidates[label] = {
                'folder': str(folder), 'public_accepted': candidate['public_accepted'],
                'initial_public_accepted': initial.get('accepted'), 'feedback_status': feedback['status'],
                'feedback_attempts': feedback['feedback_rounds_attempted'],
                'final_candidate_hash': final_hash, 'changed_files': feedback['changed_files'],
                'patch_error_counts': dict(error_counts),
                'final_validation_receipts': final_validation(folder / 'feedback'),
                'independent_evidence_scope': independent_scope,
            }
        hashes = {v['final_candidate_hash'] for v in candidates.values()}
        counts['all_four_final_hash_equal'] += len(hashes) == 1
        counts['chosen_final_hash_equals_base'] += candidates[chosen]['final_candidate_hash'] == candidates['base1']['final_candidate_hash']
        counts['unresolved_with_any_public_accepted_alternative'] += not row['resolved'] and any(v['public_accepted'] for v in candidates.values())
        old_harness = old['tasks']['harness2'][task]
        old_control = old['tasks']['no_harness'][task]
        tasks[task] = {
            'chosen': chosen, 'resolved': row['resolved'], 'public_accepted': chosen_public,
            'selection': str(selection_path), 'selection_sha256': sha(selection_path),
            'changed_delivery': selection['changed_delivery'],
            'historical_control_resolved': old_control.get('resolved') is True,
            'historical_harness_resolved': old_harness.get('resolved') is True,
            'independent_groups': {g: {'passed': data['passed'], 'tests_run': data['tests_run'],
                                       'failures': data['failures'], 'errors': data['errors']}
                                   for g, data in row['grade']['groups'].items()},
            'final_patch': str(Path(selection['chosen_folder']) / 'grading/patch.diff'),
            'candidates': candidates,
        }
    assert len(tasks) == 50 and sum(t['resolved'] for t in tasks.values()) == 25
    output = {
        'schema': 'harness2-selection-audit-v1', 'source': str(BATCH),
        'model_calls': 0, 'tests_run': 0,
        'policy': 'public-preserve-v1', 'priority': list(PRIORITY),
        'scope': 'Read saved public receipts and already-recorded final independent grades only. Non-delivered variants remain ungraded unless hash-identical to delivered candidate. No posthoc re-selection score.',
        'input_hashes': {'report.json': sha(BATCH / 'report.json'), 'comparison.json': sha(BATCH / 'comparison.json'),
                         'historical/report.json': sha(BATCH / 'historical/report.json'),
                         'selector_source': sha(BATCH / 'implementation/integrations/harness2_selection.py')},
        'counts': dict(counts), 'candidate_label_counts': {k: dict(v) for k, v in label_counts.items()},
        'public_accepted_independent_failed': [k for k, t in tasks.items() if t['public_accepted'] and not t['resolved']],
        'public_not_accepted_independent_passed': [k for k, t in tasks.items() if not t['public_accepted'] and t['resolved']],
        'fallback_tasks': [k for k, t in tasks.items() if t['changed_delivery']],
        'tasks': tasks,
    }
    (OUT / 'selection-analysis.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: output[k] for k in ('counts', 'candidate_label_counts', 'public_accepted_independent_failed', 'public_not_accepted_independent_passed', 'fallback_tasks')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    audit()
