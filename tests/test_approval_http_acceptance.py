import json

import pytest

pytest.importorskip('langgraph.checkpoint.sqlite')
pytest.importorskip('fastapi')
pytest.importorskip('uvicorn')
pytest.importorskip('psutil')

from deploy.approval_acceptance import ApprovalAcceptance


def test_real_http_approval_restart_and_execution_crash(tmp_path):
    acceptance = ApprovalAcceptance(tmp_path)
    try:
        acceptance.run()
    finally:
        acceptance.finish()
    report = json.loads((tmp_path / 'acceptance.json').read_text(encoding='utf-8'))
    assert report['status'] == 'passed' and all(report['checks'].values())
    assert report['cleanup_stopped_tracked_workers'] and acceptance.process is None
    assert all('returncode' in server for server in report['servers'])
    with pytest.raises(OSError):
        acceptance.request('/health')
