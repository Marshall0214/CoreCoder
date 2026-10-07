import json
from types import SimpleNamespace as S

import pytest

from docs.experiments import provider_compare_v1 as experiment
from docs.experiments import provider_compare_worker_v1 as worker
from evals.runtime import Events
from evals.schema import RunConfig


def response(model='deepseek-flash', content='{"edits": []}', finish='stop', reasoning=None, tokens=0, usage=True):
    return S(model=model, system_fingerprint='test-fingerprint',
             choices=[S(finish_reason=finish, message=S(content=content, reasoning_content=reasoning, tool_calls=None))],
             usage=S(prompt_tokens=30, completion_tokens=10, total_tokens=40,
                     completion_tokens_details=S(reasoning_tokens=tokens), prompt_cache_hit_tokens=20,
                     prompt_cache_miss_tokens=10) if usage else None)


class Client:
    def __init__(self, reply):
        self.reply, self.requests = reply, []
        self.chat = S(completions=S(create=self.create))
    def create(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def setup(tmp_path, reply, provider='deepseek'):
    events = Events(tmp_path / 'trace.jsonl', 'provider-test')
    client = Client(reply)
    inner = worker.Provider(provider, events, client=client)
    llm = worker.CheckedBudgetLLM(inner, RunConfig(token_budget=15000, max_output_tokens=2048), events)
    return inner, llm, client


@pytest.mark.parametrize('provider,model', [('deepseek', 'deepseek-flash'), ('qwen', 'qwen3.5:27b')])
def test_explicit_nonthinking_wire_and_usage(tmp_path, provider, model):
    inner, llm, client = setup(tmp_path, response(model=model), provider)
    result = llm.chat([{'role': 'user', 'content': 'patch'}], tools=[])
    request = client.requests[0]
    assert request['stream'] is False and request['temperature'] == 0 and request['max_tokens'] == 2048
    assert request['top_p'] == 1
    if provider == 'deepseek':
        assert request['extra_body'] == {'thinking': {'type': 'disabled'}}
    else:
        assert request['reasoning_effort'] == 'none'
    assert 'response_format' not in request and 'tools' not in request
    assert result.prompt_tokens == 30 and result.completion_tokens == 10
    assert llm.metrics()['budget_accounted_tokens'] == 40 and inner.calls[0]['system_fingerprint'] == 'test-fingerprint'


@pytest.mark.parametrize('reply,reason', [
    (response(finish='length'), 'output_truncated'),
    (response(reasoning='private chain text'), 'unexpected_thinking'),
    (response(tokens=4), 'unexpected_thinking'),
    (response(content=''), 'empty_final_answer'),
    (response(model='unexpected-model'), 'model_identity_mismatch'),
])
def test_unusable_response_is_rejected_after_usage_charge(tmp_path, reply, reason):
    _, llm, _ = setup(tmp_path, reply)
    with pytest.raises(worker.InvalidCompletion, match=reason):
        llm.chat([{'role': 'user', 'content': 'patch'}], tools=[])
    assert llm.metrics()['budget_accounted_tokens'] == 40
    assert all('private chain text' not in p.read_text(encoding='utf-8') for p in tmp_path.rglob('*') if p.is_file())


def test_missing_usage_remains_unknown_and_reserves_budget(tmp_path):
    _, llm, _ = setup(tmp_path, response(usage=False))
    llm.chat([{'role': 'user', 'content': 'patch'}], tools=[])
    metrics = llm.metrics()
    assert metrics['prompt_tokens'] is None and metrics['missing_usage_calls'] == 1
    assert metrics['budget_accounted_tokens'] >= 2048


def test_transport_failure_has_one_attempt_and_no_raw_error_persistence(tmp_path):
    inner, llm, client = setup(tmp_path, OSError('sensitive exception text'))
    with pytest.raises(OSError):
        llm.chat([{'role': 'user', 'content': 'patch'}], tools=[])
    assert len(client.requests) == 1 and inner.calls[0]['response_received'] is False
    assert inner.calls[0]['error_type'] == 'OSError' and 'error' not in inner.calls[0]


def test_only_explicit_deepseek_key_is_selected(tmp_path, monkeypatch):
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'unrelated-key')
    monkeypatch.setenv('CORECODER_API_KEY', 'unrelated-key')
    with pytest.raises(ValueError, match='DEEPSEEK_API_KEY'):
        worker.deepseek_key(tmp_path)
    (tmp_path / '.env').write_text('DEEPSEEK_API_KEY=file-key\n', encoding='utf-8')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'environment-key')
    assert worker.deepseek_key(tmp_path) == 'file-key'


def test_client_disables_sdk_retries_and_does_not_persist_key(tmp_path, monkeypatch):
    captured = {}
    def create(**kwargs):
        captured.update(kwargs)
        return Client(response())
    monkeypatch.setattr(worker, 'OpenAI', create)
    events = Events(tmp_path / 'trace.jsonl', 'credentials')
    worker.Provider('deepseek', events, key='local-test-key')
    assert captured['max_retries'] == 0 and captured['timeout'] == 60
    assert not list(tmp_path.rglob('request.json'))


def test_invalid_task_selection_never_loads_key_or_starts_model(tmp_path, monkeypatch):
    monkeypatch.setattr(experiment.preparation, 'prepare', lambda output: ([{'task_id': 'a'}], [{}]))
    monkeypatch.setattr(worker, 'deepseek_key', lambda *args: pytest.fail('No credentials for invalid selection'))
    with pytest.raises(ValueError, match='selection'):
        experiment.run(tmp_path / 'output', ['unknown'])


@pytest.mark.parametrize('provider', ['qwen', 'deepseek'])
def test_worker_entrypoint_uses_config_copy_and_persists_result(tmp_path, monkeypatch, provider):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'test-key')
    original = RunConfig(model='qwen3.5:27b', base_url='http://localhost:11434/v1')
    monkeypatch.setattr(worker.unified.repair, 'config', lambda: original)
    monkeypatch.setattr(worker.unified.repair, 'check_identity', lambda config: None)
    monkeypatch.setattr(worker, 'deepseek_key', lambda: 'test-key')
    client = Client(response(model=worker.PROVIDERS[provider]['model']))
    client.close = lambda: None
    monkeypatch.setattr(worker, 'OpenAI', lambda **kwargs: client)
    def candidate(llm, job, events, result):
        assert llm.config.model == worker.PROVIDERS[provider]['model']
        llm.chat([{'role': 'user', 'content': 'patch'}], tools=[])
        result['status'] = 'completed'
    monkeypatch.setattr(worker.unified, 'run_candidate', candidate)
    path = tmp_path / 'job.json'
    path.write_text(json.dumps({'provider': provider}), encoding='utf-8')
    worker.worker(path)
    result = json.loads((tmp_path / 'worker-result.json').read_text(encoding='utf-8'))
    assert result['status'] == 'completed' and len(result['provider_calls']) == 1
    assert original.model == 'qwen3.5:27b' and len(client.requests) == 1
