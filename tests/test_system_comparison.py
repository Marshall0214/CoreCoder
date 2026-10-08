from types import SimpleNamespace

import pytest

from docs.experiments import system_comparison_v1 as comparison
from docs.experiments import system_comparison_worker_v1 as worker
from evals.runtime import Events


def provider(tmp_path, finish='tool_calls', reasoning=None):
    message = SimpleNamespace(content=None, reasoning_content=reasoning, reasoning=None,
                              tool_calls=[SimpleNamespace(id='1', function=SimpleNamespace(
                                  name='read_file', arguments='{"file_path":"code.py"}'))])
    response = SimpleNamespace(model='qwen3.5:27b', usage=SimpleNamespace(
        prompt_tokens=100, completion_tokens=20, total_tokens=120, completion_tokens_details=None),
        choices=[SimpleNamespace(message=message, finish_reason=finish)])
    requests = []
    def create(**kwargs):
        requests.append(kwargs)
        return response
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    events = Events(tmp_path / 'trace.jsonl', 'test')
    inner = worker.ToolProvider('qwen', events, client=client)
    return worker.ToolBudget(inner, worker.previous.repair.config(), events), requests


def test_original_tool_calls_are_allowed_and_charged(tmp_path):
    budget, requests = provider(tmp_path)
    tools = [{'type': 'function', 'function': {'name': 'read_file'}}]
    response = budget.chat([{'role': 'user', 'content': 'repair'}], tools=tools)
    assert response.tool_calls[0].arguments == {'file_path': 'code.py'}
    assert budget.metrics()['budget_accounted_tokens'] == 120
    assert requests[0]['tools'] == tools and requests[0]['reasoning_effort'] == 'none'
    assert requests[0]['max_tokens'] == 2048 and requests[0]['stream'] is False


@pytest.mark.parametrize('finish,reasoning', [('length', None), ('stop', 'thinking')])
def test_invalid_output_still_costs_tokens(tmp_path, finish, reasoning):
    budget, _ = provider(tmp_path, finish, reasoning)
    with pytest.raises(worker.previous.baseline.InvalidCompletion):
        budget.chat([{'role': 'user', 'content': 'repair'}])
    assert budget.metrics()['budget_accounted_tokens'] == 120
    assert budget.metrics()['llm_calls'] == 1


def test_historical_agent_is_loaded_from_snapshot(tmp_path):
    engine = comparison.extract_engine(tmp_path)
    original = worker.upstream(engine)
    from corecoder.agent import Agent
    assert original.Agent is not Agent
    assert original.Agent.__module__ == 'benchmark_upstream_corecoder.agent'
    import inspect
    assert __import__('pathlib').Path(inspect.getfile(original.Agent)).resolve() == engine / 'agent.py'


def test_summary_retains_failure_and_missing_usage():
    rows = [{'policy': 'original', 'task_id': 'one', 'accepted': False,
             'worker': {'status': 'completed', 'metrics': {'llm_calls': 2, 'budget_accounted_tokens': 200}},
             'verification': {'groups': {'Controls': {'passed': True}}}, 'process': {'seconds': 1}},
            {'policy': 'original', 'task_id': 'two', 'accepted': False,
             'worker': {'status': 'timeout', 'metrics': None},
             'verification': {}, 'process': {'seconds': 600}}]
    summary = comparison.summarize(rows)
    assert summary['original']['tasks'] == 2 and summary['original']['passed'] == 0
    assert summary['original']['false_completed'] == ['one']
    assert summary['original']['missing_worker_results'] == 1
    assert summary['original']['calls'] == 2 and summary['original']['tokens'] == 200
    assert summary['retrieval']['tasks'] == 0


def test_full_worker_can_restore_its_workspace(tmp_path, monkeypatch):
    import json
    import shutil
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'code.py').write_text('original', encoding='utf-8')
    original = tmp_path / 'original-workspace'
    shutil.copytree(workspace, original)
    path = tmp_path / 'job.json'
    path.write_text(json.dumps({'workspace': str(workspace), 'policy': 'full'}), encoding='utf-8')
    fake = SimpleNamespace(calls=[], client=SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(worker.previous, 'Provider', lambda *args: fake)
    monkeypatch.setattr(worker.previous, 'CheckedBudgetLLM', lambda *args: SimpleNamespace(metrics=dict))
    monkeypatch.setattr(worker.previous.repair, 'check_identity', lambda *args: None)
    def rollback(llm, job, events):
        (workspace / 'code.py').write_text('bad', encoding='utf-8')
        worker.guarded.restore(workspace, original, tmp_path)
        return {'status': 'failed_public_validation', 'published': False}
    monkeypatch.setattr(worker.guarded, 'run_candidate', rollback)
    worker.worker(path)
    assert (workspace / 'code.py').read_text() == 'original'
    result = json.loads((tmp_path / 'worker-result.json').read_text())
    assert result['status'] == 'failed_public_validation'
