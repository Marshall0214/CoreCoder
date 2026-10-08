import json
from types import SimpleNamespace

import pytest

from docs.experiments import guarded_provider_compare_v2 as experiment
from evals.schema import RunConfig


@pytest.mark.parametrize('policy', ['qwen', 'deepseek'])
def test_worker_changes_provider_without_changing_budget(tmp_path, monkeypatch, policy):
    original = RunConfig(model='qwen3.5:27b', base_url='http://localhost:11434/v1',
                         max_rounds=2, token_budget=15000, max_output_tokens=2048)
    monkeypatch.setattr(experiment.previous.repair, 'config', lambda: original)
    monkeypatch.setattr(experiment.previous.repair, 'check_identity', lambda config: None)
    monkeypatch.setattr(experiment.adapters, 'deepseek_key', lambda: 'guarded-test-key')
    # Ensure the worker makes the event redactor aware of the key before writing.
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    closed = []
    provider = SimpleNamespace(model='test-model', calls=[], client=SimpleNamespace(close=lambda: closed.append(True)))
    monkeypatch.setattr(experiment.adapters, 'Provider', lambda *args: provider)
    captured = []

    def candidate(llm, job, events):
        captured.append(llm.config)
        return {'status': 'completed', 'published': True, 'diagnostic': 'guarded-test-key'}

    monkeypatch.setattr(experiment.guarded, 'run_candidate', candidate)
    path = tmp_path / 'job.json'
    path.write_text(json.dumps({'policy': policy}), encoding='utf-8')
    experiment.worker(path)
    result_text = (tmp_path / 'worker-result.json').read_text(encoding='utf-8')
    result = json.loads(result_text)
    assert result['status'] == 'completed' and closed == [True]
    changed = captured[0]
    assert changed.model == experiment.adapters.PROVIDERS[policy]['model']
    assert changed.base_url == experiment.adapters.PROVIDERS[policy]['base_url']
    assert changed.max_rounds == original.max_rounds == 2
    assert changed.token_budget == original.token_budget == 15000
    assert changed.max_output_tokens == original.max_output_tokens == 2048
    assert original.model == 'qwen3.5:27b'
    if policy == 'deepseek':
        assert 'guarded-test-key' not in result_text


def test_worker_exception_restores_only_owned_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'code.py').write_text('original', encoding='utf-8')
    original = tmp_path / 'original-workspace'
    original.mkdir()
    (original / 'code.py').write_text('original', encoding='utf-8')
    monkeypatch.setattr(experiment.previous.repair, 'check_identity', lambda config: None)
    monkeypatch.setattr(experiment.adapters, 'Provider', lambda *args: SimpleNamespace(
        model='test-model', calls=[], client=SimpleNamespace(close=lambda: None)))

    def candidate(*args):
        (workspace / 'code.py').write_text('damaged', encoding='utf-8')
        raise OSError('do not persist raw provider errors')

    monkeypatch.setattr(experiment.guarded, 'run_candidate', candidate)
    path = tmp_path / 'job.json'
    path.write_text(json.dumps({'policy': 'qwen', 'workspace': str(workspace)}), encoding='utf-8')
    experiment.worker(path)
    result = json.loads((tmp_path / 'worker-result.json').read_text(encoding='utf-8'))
    assert (workspace / 'code.py').read_text(encoding='utf-8') == 'original'
    assert result['status'] == 'agent_error' and result['error_type'] == 'OSError'
    assert not result['published'] and 'error' not in result


def test_summary_does_not_count_rollback_controls_as_repair_success():
    rows = [{'policy': 'qwen', 'accepted': False, 'worker': {'metrics': None},
             'verification': {'groups': {'Controls': {'passed': True}}},
             'process': {'seconds': 1}}]
    result = experiment.summary(rows)
    assert result['qwen']['passed'] == 0 and result['qwen']['controls_passed'] == 1
    assert result['qwen']['missing_worker_results'] == 1
    assert result['deepseek']['tasks'] == 0 and result['deepseek']['passed'] == 0
