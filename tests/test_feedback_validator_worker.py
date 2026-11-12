"""A validator process crash must not leave its Docker containers behind."""
import json
import sys
from types import SimpleNamespace

import pytest

from repairflow import feedback_repair_v2 as feedback


@pytest.mark.parametrize(('payload', 'exit_code', 'reason'), [
    (None, 9, 'validator_worker_failed'),
    ('{broken', 1, 'validator_worker_result_invalid'),
    (json.dumps({'status': 'validated', 'accepted': True}), 9, 'validator_worker_exit_mismatch'),
])
def test_worker_failure_cleans_only_its_owner(tmp_path, monkeypatch, payload, exit_code, reason):
    output, owner = tmp_path / 'validation', tmp_path
    cleaned = []

    def start(command, **kwargs):
        assert command[3] == 'repairflow.patch_validator'
        assert kwargs['env']['CORECODER_SANDBOX_OWNER'] == str(owner)
        if payload is not None:
            output.mkdir()
            (output / 'report.json').write_text(payload, encoding='utf-8')
        return SimpleNamespace(returncode=exit_code, poll=lambda: exit_code)

    monkeypatch.setattr(feedback.subprocess, 'Popen', start)
    monkeypatch.setattr(feedback.runner, 'cleanup', cleaned.append)
    result = feedback.validate(tmp_path / 'before', tmp_path / 'source', ['code.py'],
                               output, tmp_path / 'checks', 'pkg', owner=owner)
    assert result['status'] == 'blocked' and not result['accepted']
    assert result['infrastructure_error'] == reason
    assert cleaned == [owner]


def test_worker_and_cleanup_failures_are_both_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(feedback.subprocess, 'Popen', lambda *a, **k:
                        SimpleNamespace(returncode=7, poll=lambda: 7))

    def fail(owner):
        raise feedback.runner.SandboxError('sandbox_control_failed')

    monkeypatch.setattr(feedback.runner, 'cleanup', fail)
    result = feedback.validate(tmp_path / 'before', tmp_path / 'source', ['code.py'],
                               tmp_path / 'validation', tmp_path / 'checks', 'pkg', owner=tmp_path)
    assert result['infrastructure_error'] == 'validator_worker_failed'
    assert 'sandbox_control_failed' in result['cleanup_error']


def test_cancel_terminates_a_real_worker_process_without_contacting_docker(tmp_path, monkeypatch):
    original = feedback.subprocess.Popen
    children, cleaned = [], []

    def start(command, **kwargs):
        if 'repairflow.patch_validator' in command:
            process = original([sys.executable, '-B', '-c', 'import time; time.sleep(60)'], **kwargs)
            children.append(process)
            return process
        return original(command, **kwargs)  # Allow terminate_tree's taskkill on Windows.

    stop = tmp_path / 'CANCEL'
    stop.touch()
    monkeypatch.setattr(feedback.subprocess, 'Popen', start)
    monkeypatch.setattr(feedback.runner, 'cleanup', cleaned.append)
    try:
        result = feedback.validate(tmp_path / 'before', tmp_path / 'source', ['code.py'],
                                   tmp_path / 'validation', tmp_path / 'checks', 'pkg',
                                   owner=tmp_path, stop_file=stop)
        assert result['status'] == 'cancelled' and not result['accepted']
        assert len(children) == 1 and children[0].poll() is not None
        assert cleaned == [tmp_path]
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
