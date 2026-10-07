import json

import pytest

pytest.importorskip('fastapi')
pytest.importorskip('uvicorn')
pytest.importorskip('psutil')

from deploy.local_acceptance import LocalAcceptance


def test_actual_http_crash_recovery_and_graceful_cleanup(tmp_path):
    acceptance = LocalAcceptance(tmp_path)
    try:
        acceptance.run()
    finally:
        acceptance.finish()
    report = json.loads((tmp_path / 'acceptance.json').read_text(encoding='utf-8'))
    assert report['status'] == 'passed' and report['checks']
    assert all(report['checks'].values()) and report['cleanup_stopped_tracked_workers']
    assert any(server['hard_stop'] for server in report['servers'])
    assert all('returncode' in server for server in report['servers'])
    assert acceptance.process is None
    with pytest.raises(OSError):
        acceptance.request('/health')


def test_existing_task_data_is_not_reused(tmp_path):
    (tmp_path / 'data').mkdir()
    marker = tmp_path / 'data' / 'keep.txt'
    marker.write_text('existing data', encoding='utf-8')
    with pytest.raises(ValueError, match='fresh directory'):
        LocalAcceptance(tmp_path)
    assert marker.read_text(encoding='utf-8') == 'existing data'
