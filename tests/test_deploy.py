import json
import subprocess

import pytest

from deploy.acceptance import Acceptance
from service import worker


@pytest.mark.parametrize('endpoint', [None, 'http://host.docker.internal:11434/v1'])
def test_worker_endpoint_is_operator_configured_without_changing_request(tmp_path, monkeypatch, endpoint):
    if endpoint is None:
        monkeypatch.delenv('CORECODER_MODEL_BASE_URL', raising=False)
    else:
        monkeypatch.setenv('CORECODER_MODEL_BASE_URL', endpoint)
    seen = []

    def run_task(task, config, output):
        seen.append(config)
        return {'status': 'passed', 'accepted': True}

    monkeypatch.setattr(worker, 'run_task', run_task)
    path = tmp_path / 'job.json'
    path.write_text(json.dumps({'request': {'suite': 'smoke', 'task_id': 'timeout-units',
                                          'mode': 'scripted', 'search_backend': 'off'}}), encoding='utf-8')
    worker.execute(path)
    assert seen[0].base_url == (endpoint or 'http://localhost:11434/v1')
    assert seen[0].model == 'qwen3.5:27b' and seen[0].token_budget == 15000
    assert json.loads((tmp_path / 'result.json').read_text())['accepted']


def test_unavailable_engine_preserves_failure_report_and_does_not_start_compose(tmp_path, monkeypatch):
    acceptance = Acceptance(tmp_path)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, '', 'Docker engine unavailable')

    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(RuntimeError):
        acceptance.run()
    acceptance.report['status'] = 'failed'
    acceptance.finish()
    assert calls == [['docker', 'info', '--format', '{{.ServerVersion}}']]
    report = json.loads((tmp_path / 'acceptance.json').read_text())
    assert report['status'] == 'failed' and not report['checks']
    assert report['retained_volume'] is None


def test_acceptance_commands_have_deadlines(tmp_path, monkeypatch):
    acceptance = Acceptance(tmp_path)

    def run(argv, **kwargs):
        assert kwargs['timeout'] == 15
        raise subprocess.TimeoutExpired(argv, 15)

    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='timed out'):
        acceptance.command(['docker', 'info'], timeout=15)
    acceptance.report['status'] = 'failed'
    acceptance.finish()
    report = json.loads((tmp_path / 'acceptance.json').read_text())
    assert report['commands'][0]['error'] == 'timeout'


def test_cleanup_still_stops_project_when_log_collection_fails(tmp_path, monkeypatch):
    acceptance = Acceptance(tmp_path)
    acceptance.started = True
    acceptance.report['status'] = 'passed'
    calls = []

    def compose(*args, **kwargs):
        calls.append(args)
        if args[0] == 'logs':
            raise RuntimeError('Log collection failed')

    monkeypatch.setattr(acceptance, 'compose', compose)
    acceptance.finish()
    assert calls == [('logs', '--no-color'), ('down',)]
    report = json.loads((tmp_path / 'acceptance.json').read_text())
    assert report['status'] == 'failed' and report['cleanup_errors'] == ['Log collection failed']
