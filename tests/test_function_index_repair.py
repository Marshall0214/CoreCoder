import hashlib
import json
import sys

import pytest

from docs.experiments import function_index_repair_v1 as repair
from evals.runner import digest, snapshot


def evidence(tmp_path, text='def needle():\r\n    return 1\r\n'):
    (tmp_path / 'source.py').write_bytes(text.encode())
    return [{'path': 'source.py', 'start_line': 1, 'end_line': len(text.splitlines()),
             'content': text, 'content_hash': hashlib.sha256(text.encode()).hexdigest()}]


def test_exact_citation_and_stale_source_rejected(tmp_path):
    rows = evidence(tmp_path)
    repair.validate_evidence(tmp_path, ['source.py'], rows)
    rows[0]['content'] = rows[0]['content'].replace('\r\n', '\n')
    with pytest.raises(ValueError, match='citation'):
        repair.validate_evidence(tmp_path, ['source.py'], rows)
    rows = evidence(tmp_path)
    (tmp_path / 'source.py').write_text('def needle():\n    return 2\n')
    with pytest.raises(ValueError, match='version'):
        repair.validate_evidence(tmp_path, ['source.py'], rows)


def test_unallowed_source_ranges_and_budget_rejected(tmp_path):
    rows = evidence(tmp_path)
    with pytest.raises(ValueError, match='allowed'):
        repair.validate_evidence(tmp_path, [], rows)
    rows[0]['start_line'] = True
    with pytest.raises(ValueError, match='citation'):
        repair.validate_evidence(tmp_path, ['source.py'], rows)
    rows = evidence(tmp_path, '# comment\n' * 700)
    with pytest.raises(ValueError, match='budget'):
        repair.validate_evidence(tmp_path, ['source.py'], rows)
    with pytest.raises(ValueError, match='five'):
        repair.validate_evidence(tmp_path, ['source.py'], rows * 6)


def test_missing_metrics_are_not_reported_as_zero_cost():
    runs = [{'policy': repair.POLICIES[0], 'worker': {'metrics': None}, 'accepted': False,
             'status': 'timeout', 'process': {'seconds': 600}}]
    summary = repair.summarize(runs)[repair.POLICIES[0]]
    assert summary['budget_accounted_tokens'] is None and summary['prompt_tokens'] is None
    assert summary['missing_metrics_runs'] == 1 and summary['statuses'] == {'timeout': 1}


def test_unfrozen_observations_fail_before_selection(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'observations.json').write_text('[]')
    with pytest.raises(ValueError, match='frozen'):
        repair.prepare(source, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('tamper', [False, True])
def test_paired_run_keeps_failures_isolates_jobs_and_detects_evidence_changes(tmp_path, monkeypatch, tamper):
    cases, bundles = [], []
    for i in range(7):
        before = tmp_path / f'task-{i}' / 'before'
        before.mkdir(parents=True)
        rows = evidence(before, 'def needle():\n    return 1\n')
        case = {'task_id': f'task-{i}', 'before': before, 'before_hash': digest(snapshot(before)),
                'description': 'Fix needle', 'allowed_files': ['source.py'], 'admission_path': tmp_path / 'admission',
                'catalog': tmp_path / 'catalog'}
        cases.append(case)
        bundles.append({'task_id': case['task_id'], 'policies': {p: {'evidence': rows} for p in repair.POLICIES}})
    output = tmp_path / 'output'
    monkeypatch.setattr(repair, 'prepare', lambda *_: (cases, bundles))
    monkeypatch.setattr(repair, 'check_identity', lambda *_: None)
    monkeypatch.setattr(repair, 'admitted_case', lambda *_: ({}, {}, tmp_path, tmp_path, {'executable': sys.executable}))
    monkeypatch.setattr(repair, 'checked_groups', lambda *_: {
        'Controls': {'passed': True}, 'Target': {'assertion_failure': True, 'execution_error': False}})
    calls = []

    def process(args, workspace, *rest):
        path = workspace.parent
        job = json.loads((path / 'job.json').read_text())
        assert set(job) == {'workspace', 'description', 'allowed_files', 'evidence'}
        assert (output / 'protocol.json').exists() and (output / 'evidence.json').exists()
        assert digest(snapshot(workspace)) == cases[0]['before_hash']
        calls.append(path.name)
        metrics = {'budget_accounted_tokens': 100, 'prompt_tokens': 80, 'completion_tokens': 20, 'missing_usage_calls': 0}
        status = 'invalid_patch' if path.name == repair.POLICIES[1] else 'completed'
        (path / 'worker-result.json').write_text(json.dumps({'status': status, 'metrics': metrics}))
        if tamper:
            (output / 'evidence.json').write_text('[]')
        return {'returncode': 0, 'timed_out': False, 'seconds': 1}

    monkeypatch.setattr(repair, 'run_process', process)
    # Target-only success is rejected when regression verification fails.
    monkeypatch.setattr(repair, 'verify', lambda *_: {'passed': False, 'target': {'passed': True}, 'regression': {'passed': False}})
    if tamper:
        with pytest.raises(ValueError, match='Frozen evidence'):
            repair.run(tmp_path, output)
        assert len(calls) == 1
    else:
        repair.run(tmp_path, output)
        report = json.loads((output / 'experiment.json').read_text())
        assert report['complete'] and len(report['runs']) == 14
        assert not any(r['accepted'] for r in report['runs'])
        assert report['summary'][repair.POLICIES[0]]['statuses'] == {'failed_verification': 7}
        assert report['summary'][repair.POLICIES[1]]['statuses'] == {'invalid_patch': 7}
        assert calls[:4] == [repair.POLICIES[0], repair.POLICIES[1], repair.POLICIES[1], repair.POLICIES[0]]
