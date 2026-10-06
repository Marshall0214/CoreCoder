import hashlib
import json

import pytest

from docs.experiments import repeat_function_index_repair_v1 as repeat


def row(task, policy, number, passed=False, status=None):
    return {'task_id': task, 'policy': policy, 'repeat': number, 'accepted': passed,
            'status': status or ('passed' if passed else 'failed_verification'),
            'worker': {'prompt_hash': policy, 'metrics': {'budget_accounted_tokens': 100,
                       'prompt_tokens': 80, 'completion_tokens': 20, 'missing_usage_calls': 0}},
            'process': {'seconds': 1}}


def test_paired_summary_counts_all_four_outcomes_and_separates_unique_tasks():
    runs = []
    policies = repeat.repair.POLICIES
    for i, outcome in enumerate(((False, False), (False, True), (True, False), (True, True))):
        for number in range(1, 4):
            runs.extend(row(str(i), p, number, passed) for p, passed in zip(policies, outcome))
    result = repeat.aggregate(runs, ['0', '1', '2', '3'], 3)
    assert result['complete'] and result['unique_tasks'] == 4 and result['expected_runs'] == 24
    assert result['paired'] == {'both_failed': 3, 'function_only': 3, 'line_only': 3, 'both_passed': 3}
    assert all(g['prompt_identical'] and g['status_consistent'] for r in result['per_task'] for g in r['policies'].values())
    assert len(result['per_repeat']) == 3


def test_partial_pairs_and_changed_status_or_prompt_are_not_marked_stable():
    policy = repeat.repair.POLICIES[0]
    runs = [row('a', policy, 1), row('a', policy, 2, status='invalid_patch')]
    runs[1]['worker']['prompt_hash'] = 'changed'
    result = repeat.aggregate(runs, ['a'], 2)
    assert not result['complete'] and result['paired'] == {'incomplete': 2}
    assert not result['per_task'][0]['policies'][policy]['status_consistent']
    assert not result['per_task'][0]['policies'][policy]['prompt_identical']


@pytest.mark.parametrize('kind', ['duplicate', 'unknown-task', 'unknown-policy', 'out-of-range'])
def test_unexpected_branches_rejected(kind):
    first = row('a', repeat.repair.POLICIES[0], 1)
    rows = [first]
    if kind == 'duplicate':
        rows.append(dict(first))
    elif kind == 'unknown-task':
        first['task_id'] = 'other'
    elif kind == 'unknown-policy':
        first['policy'] = 'other'
    else:
        first['repeat'] = 2
    with pytest.raises(ValueError, match='unexpected'):
        repeat.aggregate(rows, ['a'], 1)


def test_stopped_child_preserves_partial_results_and_never_includes_prior_runs(tmp_path, monkeypatch):
    bundles = []
    encoded = json.dumps(bundles, ensure_ascii=False, indent=2).encode().replace(b'\n', b'\r\n')
    monkeypatch.setattr(repeat, 'EVIDENCE_SHA', hashlib.sha256(encoded).hexdigest())
    monkeypatch.setattr(repeat.repair, 'prepare', lambda *_: ([{'task_id': 'a'}], bundles))
    monkeypatch.setattr(repeat.repair, 'check_identity', lambda *_: None)

    def child(_, output):
        output.mkdir()
        number = int(output.name.split('-')[-1])
        runs = [row('a', p, number) for p in repeat.repair.POLICIES]
        if number == 2:
            runs = runs[:1]
        data = {'protocol': {'evidence_sha256': repeat.EVIDENCE_SHA, 'config': repeat.repair.config().to_dict()},
                'runs': [{k: v for k, v in r.items() if k != 'repeat'} for r in runs]}
        (output / 'experiment.json').write_text(json.dumps(data))
        if number == 2:
            raise RuntimeError('interrupted child')

    monkeypatch.setattr(repeat.repair, 'run', child)
    output = tmp_path / 'output'
    with pytest.raises(RuntimeError, match='interrupted'):
        repeat.run(tmp_path, output, 2)
    report = json.loads((output / 'experiment.json').read_text())
    assert not report['complete'] and len(report['runs']) == 3
    assert report['paired'] == {'both_failed': 1, 'incomplete': 1}
    assert report['protocol']['prior_runs_included'] is False


def test_invalid_repeat_count_fails_before_source_reads(tmp_path):
    for value in (0, 11, True, 1.5):
        with pytest.raises(ValueError, match='Repeat count'):
            repeat.run(tmp_path, tmp_path / 'output', value)
    assert not (tmp_path / 'output').exists()
