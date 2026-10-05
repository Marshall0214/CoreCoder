import hashlib
import json

import pytest

from docs.scripts.audit_event_comparison import frozen_runs


def batch(tmp_path):
    state = {'completed': True, 'stop_reason': None, 'planned_runs': 1, 'run_ids': {'v7': ['run-1']}}
    freeze = {'implementation': {'source_hash': 'frozen'}}
    directory = tmp_path / 'v7/run-1'
    directory.mkdir(parents=True)
    code = b'import unittest\n'
    (directory / 'public-contract-checks.py').write_bytes(code)
    report = {'task_id': 'event-replay', 'run_id': 'run-1', 'implementation': {'source_hash': 'frozen'},
              'worker': {'public_checks': {'code_hash': hashlib.sha256(code).hexdigest()}}}
    for path, value in [(tmp_path / 'comparison.json', state), (tmp_path / 'freeze.json', freeze),
                        (directory / 'report.json', report)]:
        path.write_text(json.dumps(value), encoding='utf-8')
    return directory


def test_frozen_report_loading_is_read_only(tmp_path):
    directory = batch(tmp_path)
    before = (directory / 'report.json').read_bytes()
    rows, _ = frozen_runs(tmp_path)
    assert len(rows) == 1 and rows[0][0] == 'v7'
    assert (directory / 'report.json').read_bytes() == before


@pytest.mark.parametrize('change', ['checks', 'source', 'incomplete', 'missing', 'duplicate', 'traversal'])
def test_audit_rejects_invalid_frozen_records(tmp_path, change):
    directory = batch(tmp_path)
    state = json.loads((tmp_path / 'comparison.json').read_text())
    if change == 'checks':
        (directory / 'public-contract-checks.py').write_bytes(b'changed')
    elif change == 'source':
        report = json.loads((directory / 'report.json').read_text())
        report['implementation']['source_hash'] = 'changed'
        (directory / 'report.json').write_text(json.dumps(report))
    elif change == 'incomplete':
        state['completed'] = False
    elif change == 'missing':
        state['planned_runs'] = 2
    elif change == 'duplicate':
        state['run_ids']['v7'].append('run-1')
    else:
        state['run_ids'] = {'../v7': ['run-1']}
    (tmp_path / 'comparison.json').write_text(json.dumps(state))
    with pytest.raises(ValueError):
        frozen_runs(tmp_path)
