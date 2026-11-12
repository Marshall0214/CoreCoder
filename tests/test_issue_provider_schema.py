"""Optional native Ollama schemas; all requests are intercepted locally."""
import copy
import json
import time

import pytest

from repairflow import issue_providers as providers

SCHEMA = {
    'type': 'object',
    'properties': {'action': {'type': 'string', 'enum': ['finish']},
                   'arguments': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
    'required': ['action', 'arguments'],
    'additionalProperties': False,
}


def intercepted_provider(monkeypatch, *, done_reason='stop', thinking=None, tool_calls=None):
    requests, handlers = [], []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            assert limit == 4_000_001
            message = {'content': '{"action":"finish","arguments":{}}'}
            if thinking is not None:
                message['thinking'] = thinking
            if tool_calls is not None:
                message['tool_calls'] = tool_calls
            return json.dumps({'done': True, 'done_reason': done_reason,
                               'model': 'qwen3.5:27b', 'message': message,
                               'prompt_eval_count': 12, 'eval_count': 5}).encode()

    class Opener:
        def open(self, request, timeout):
            assert 0 < timeout <= 30
            requests.append(request)
            return Response()

    def build_opener(*items):
        handlers.extend(items)
        return Opener()

    monkeypatch.setattr(providers.urllib.request, 'build_opener', build_opener)
    provider = providers.OllamaProvider('qwen3.5:27b', time.monotonic() + 30)
    return provider, requests, handlers


def test_legacy_request_keeps_json_format_and_generation_defaults(monkeypatch):
    provider, requests, _ = intercepted_provider(monkeypatch)
    messages = [{'role': 'user', 'content': 'Inspect the prepared source.'}]
    provider.chat(messages, tools=[])
    assert json.loads(requests[0].data) == {
        'model': 'qwen3.5:27b', 'messages': messages, 'stream': False, 'think': False,
        'format': 'json', 'options': {'temperature': 0, 'num_predict': 32768, 'num_ctx': 65536},
    }


def test_explicit_schema_uses_native_format_without_mutating_caller(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'schema-test-secret-never-sent')
    monkeypatch.setenv('HTTP_PROXY', 'http://untrusted.invalid:7890')
    provider, requests, handlers = intercepted_provider(monkeypatch)
    schema = copy.deepcopy(SCHEMA)
    response = provider.chat([], tools=[], max_tokens=-1, response_schema=schema)
    payload = json.loads(requests[0].data)
    assert payload['format'] == schema == SCHEMA
    assert payload['think'] is False and payload['stream'] is False
    assert payload['options'] == {'temperature': 0, 'num_predict': -1, 'num_ctx': 65536}
    assert 'response_format' not in payload and 'tools' not in payload
    assert requests[0].full_url == 'http://127.0.0.1:11434/api/chat'
    assert not requests[0].has_header('Authorization')
    assert 'schema-test-secret' not in requests[0].data.decode()
    assert handlers[0].proxies == {} and isinstance(handlers[1], providers.NoRedirect)
    assert response.prompt_tokens == 12 and response.completion_tokens == 5
    assert response.reported_usage == {'prompt_tokens': 12, 'completion_tokens': 5}
    assert provider.calls[0]['native_usage'] == {'prompt_eval_count': 12, 'eval_count': 5}
    assert provider.calls[0]['usage_known'] is True
    assert provider.calls[0]['thinking_requested'] is False


@pytest.mark.parametrize('schema', [
    'json', [], 1, True, {},
    {'type': 'object', 'bad': float('nan')},
    {'type': 'object', 'bad': float('inf')},
    {'type': 'object', 'bad': {'not', 'serializable'}},
])
def test_invalid_schema_is_rejected_before_network_or_call_count(monkeypatch, schema):
    provider, requests, handlers = intercepted_provider(monkeypatch)
    with pytest.raises(ValueError):
        provider.chat([], response_schema=schema)
    assert not requests and not handlers and provider.calls == []


@pytest.mark.parametrize(('options', 'status'), [
    ({'done_reason': 'length'}, 'incomplete_model_response'),
    ({'thinking': 'unexpected reasoning'}, 'unexpected_model_response'),
    ({'tool_calls': [{'function': {'name': 'finish'}}]}, 'unexpected_model_response'),
])
def test_schema_does_not_relax_finish_or_response_contract(monkeypatch, options, status):
    provider, requests, _ = intercepted_provider(monkeypatch, **options)
    with pytest.raises(providers.ProviderFailure) as caught:
        provider.chat([], response_schema=SCHEMA)
    assert caught.value.status == status
    assert caught.value.reported_usage == {'prompt_tokens': 12, 'completion_tokens': 5}
    assert provider.calls[0]['failure'] == status
    assert json.loads(requests[0].data)['format'] == SCHEMA


def test_schema_does_not_enable_tool_requests(monkeypatch):
    provider, requests, handlers = intercepted_provider(monkeypatch)
    with pytest.raises(ValueError):
        provider.chat([], tools=[{'name': 'read_file'}], response_schema=SCHEMA)
    assert not requests and not handlers and provider.calls == []
