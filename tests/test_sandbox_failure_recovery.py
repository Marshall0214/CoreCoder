"""Infrastructure errors must never publish a candidate patch or spend a retry."""
import pytest

from repairflow import checks
from repairflow.engine import execute
from sandbox import runner
from tests.repair_bundle_fixture import bundle


def test_mid_run_sandbox_error_rolls_back_and_reports(tmp_path, monkeypatch):
    task = bundle(tmp_path / 'sample')
    monkeypatch.setenv('CORECODER_TEST_BACKEND', 'docker')
    policy = {'backend': 'docker', 'image_id': 'sha256:' + 'a' * 64}
    monkeypatch.setattr(runner, 'preflight', lambda: policy)
    calls = []

    def fail(*args, **kwargs):
        calls.append(args)
        raise runner.SandboxError('sandbox_oom')
    monkeypatch.setattr(checks, 'public_check', fail)
    monkeypatch.setattr(checks, 'verify', fail)
    report = execute(task, 'replay', tmp_path / 'run')
    assert report['status'] == 'sandbox_oom' and not report['accepted']
    assert report['original_unchanged'] and report['fresh_model_calls'] == 0
    assert (tmp_path / 'run/patch.diff').read_text() == ''
    assert 'return x + 1' in (tmp_path / 'run/workspace/src/pkg/__init__.py').read_text()
    assert len(calls) == 1  # Stop on infrastructure failure, without independent execution or model retry.
    assert runner.ACTIVE_POLICY.get() is None


def test_policy_context_resets_on_preflight_error(tmp_path, monkeypatch):
    monkeypatch.setenv('CORECODER_TEST_BACKEND', 'docker')
    monkeypatch.setattr(runner, 'preflight', lambda: (_ for _ in ()).throw(runner.SandboxError('sandbox_image_missing')))
    with pytest.raises(runner.SandboxError):
        execute(bundle(tmp_path / 'sample'), 'replay', tmp_path / 'run')
    assert runner.ACTIVE_POLICY.get() is None
