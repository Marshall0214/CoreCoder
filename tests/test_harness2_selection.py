"""Public-only candidate retention, with stale/tampered receipts rejected."""
import pytest

from evals.runner import digest, snapshot
from integrations import harness2 as bridge
from integrations import harness2_selection as selection


def setup(tmp_path, monkeypatch):
    checks = tmp_path / 'public'
    checks.mkdir()
    (checks / 'test_admission.py').write_text('# frozen public checks', encoding='utf-8')
    config = {'checks': str(checks), 'package': 'pkg'}
    monkeypatch.setattr(selection, 'verify_options', lambda supplied: None if supplied == config else pytest.fail('config'))
    public_hash = None
    rows = []
    passed = {'tests_run': 1, 'successful': True, 'returncode': 0, 'errors': 0, 'failures': 0,
              'skipped': 0, 'expected_failures': 0, 'unexpected_successes': 0, 'timed_out': False}
    for label, accepted in [('agg1', False), ('base1', True), ('inv1', True), ('dom1', False)]:
        folder = tmp_path / label
        bridge.write(folder / 'public.json', {'instance_id': 'example'})
        public_hash = bridge.sha(folder / 'public.json')
        bridge.write(folder / 'job.json', {'public_sha256': public_hash, 'source_hash': 'baseline', 'public_feedback': config})
        workspace = folder / 'feedback/workspace'
        workspace.mkdir(parents=True)
        (workspace / 'code.py').write_text('x = 1\n', encoding='utf-8')
        candidate_hash = digest(snapshot(workspace))
        bridge.write(folder / 'feedback/protocol.json', {'baseline_hash': 'baseline',
                     'public_checks_hash': digest(snapshot(checks)), 'source_root': '.'})
        bridge.write(folder / 'feedback/report.json', {'status': 'ready_for_review' if accepted else 'feedback_round_limit',
                     'accepted': accepted, 'original_inputs_unchanged': True, 'final_candidate_hash': candidate_hash})
        bridge.write(folder / 'feedback/validation-000/report.json', {'candidate_hash': candidate_hash,
                     'baseline_hash': 'baseline', 'public_checks_hash': digest(snapshot(checks)), 'status': 'validated',
                     'accepted': accepted, 'independent_grading_used': False,
                     'public_checks': {'Reproduce': passed, 'Preserve': passed}})
        rows.append({'label': label, 'folder': str(folder)})
    return rows, public_hash, config


def test_public_success_is_preserved_without_private_grades(tmp_path, monkeypatch):
    rows, public_hash, config = setup(tmp_path, monkeypatch)
    # This file must never be read or used for choosing a candidate.
    (tmp_path / 'grading.json').write_text('not even JSON: choose dom1', encoding='utf-8')
    result = selection.select(rows, 'agg1', public_hash, 'baseline', config)
    assert result['chosen_label'] == 'base1' and result['changed_delivery']
    assert result['model_calls'] == 0 and not result['independent_grading_used']
    assert selection.select(list(reversed(rows)), None, public_hash, 'baseline', config)['chosen_label'] == 'base1'


@pytest.mark.parametrize('tamper', ['workspace', 'checks_hash', 'zero_tests', 'task', 'receipt_hash'])
def test_untrustworthy_success_cannot_replace_final(tmp_path, monkeypatch, tamper):
    rows, public_hash, config = setup(tmp_path, monkeypatch)
    rows = [row for row in rows if row['label'] != 'inv1']
    folder = tmp_path / 'base1'
    path = folder / 'feedback/validation-000/report.json'
    if tamper == 'workspace':
        (folder / 'feedback/workspace/code.py').write_text('changed', encoding='utf-8')
    elif tamper == 'task':
        bridge.write(folder / 'public.json', {'instance_id': 'another'})
    else:
        receipt = bridge.read(path)
        if tamper == 'checks_hash':
            receipt['public_checks_hash'] = 'different'
        elif tamper == 'receipt_hash':
            receipt['candidate_hash'] = 'different'
        else:
            receipt['public_checks']['Reproduce']['tests_run'] = 0
        bridge.write(path, receipt)
    result = selection.select(rows, 'agg1', public_hash, 'baseline', config)
    assert result['chosen_label'] == 'agg1'
    assert not result['candidates']['base1']['public_accepted']


def test_publicly_accepted_final_keeps_priority_and_no_success_is_fabricated(tmp_path, monkeypatch):
    rows, public_hash, config = setup(tmp_path, monkeypatch)
    final = tmp_path / 'agg1/feedback'
    report = bridge.read(final / 'report.json')
    report.update(status='ready_for_review', accepted=True)
    bridge.write(final / 'report.json', report)
    receipt = bridge.read(final / 'validation-000/report.json')
    receipt['accepted'] = True
    bridge.write(final / 'validation-000/report.json', receipt)
    assert selection.select(rows, 'agg1', public_hash, 'baseline', config)['chosen_label'] == 'agg1'
    assert selection.select([], None, public_hash, 'baseline', config)['chosen_label'] is None


def test_duplicate_labels_cannot_override_another_receipt(tmp_path, monkeypatch):
    rows, public_hash, config = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='unique'):
        selection.select(rows + [rows[0]], 'agg1', public_hash, 'baseline', config)
