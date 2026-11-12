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


@pytest.mark.parametrize('reported_image', ['sha256:' + 'a' * 64, 'sha256:' + 'b' * 64, None])
def test_worker_uses_pinned_image_instead_of_ambient_and_checks_receipt(tmp_path, monkeypatch, reported_image):
    pinned = 'sha256:' + 'a' * 64
    output, cleaned = tmp_path / 'validation', []
    monkeypatch.setenv('CORECODER_SANDBOX_IMAGE', 'ambient-custom:latest')

    def start(command, **kwargs):
        assert kwargs['env']['CORECODER_SANDBOX_IMAGE'] == pinned
        output.mkdir()
        (output / 'report.json').write_text(json.dumps({'status': 'validated', 'accepted': True,
                                                       'sandbox': {'image_id': reported_image}}), encoding='utf-8')
        return SimpleNamespace(returncode=0, poll=lambda: 0)

    monkeypatch.setattr(feedback.subprocess, 'Popen', start)
    monkeypatch.setattr(feedback.runner, 'cleanup', cleaned.append)
    result = feedback.validate(tmp_path / 'before', tmp_path / 'source', ['code.py'],
                               output, tmp_path / 'checks', 'pkg', owner=tmp_path, sandbox_image_id=pinned)
    if reported_image == pinned:
        assert result['accepted'] is True and not cleaned
    else:
        assert result['status'] == 'blocked' and result['accepted'] is False
        assert result['infrastructure_error'] == 'validator_worker_image_mismatch'
        assert result['expected_image_id'] == pinned and result['actual_image_id'] == reported_image
        assert cleaned == [tmp_path]


def test_unpinned_worker_retains_legacy_ambient_image(tmp_path, monkeypatch):
    output = tmp_path / 'validation'
    monkeypatch.setenv('CORECODER_SANDBOX_IMAGE', 'ambient-custom:latest')

    def start(command, **kwargs):
        assert kwargs['env']['CORECODER_SANDBOX_IMAGE'] == 'ambient-custom:latest'
        output.mkdir()
        (output / 'report.json').write_text(json.dumps({'status': 'validated', 'accepted': True}), encoding='utf-8')
        return SimpleNamespace(returncode=0, poll=lambda: 0)

    monkeypatch.setattr(feedback.subprocess, 'Popen', start)
    result = feedback.validate(tmp_path / 'before', tmp_path / 'source', ['code.py'],
                               output, tmp_path / 'checks', 'pkg', owner=tmp_path)
    assert result['accepted'] is True


@pytest.mark.parametrize('image', ['custom:latest', 'sha256:abc', 123, 'sha256:' + 'A' * 64])
def test_worker_rejects_mutable_or_invalid_pinned_image_before_start(tmp_path, monkeypatch, image):
    monkeypatch.setattr(feedback.subprocess, 'Popen', lambda *a, **k: pytest.fail('Must not start a worker'))
    with pytest.raises(ValueError, match='immutable sandbox image ID'):
        feedback.validate(tmp_path / 'before', tmp_path / 'source', ['code.py'],
                          tmp_path / 'validation', tmp_path / 'checks', 'pkg', owner=tmp_path,
                          sandbox_image_id=image)


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
