"""Measured zero, missing counters and failed inference must remain distinguishable."""
import json
import time

import pytest

from deploy.langfuse.verify_usage import compare
from evals.runtime import BudgetLLM, Events
from evals.schema import RunConfig
from repairflow import issue_providers as providers
from repairflow.telemetry import Telemetry
from tests.test_telemetry import TASK, Client


def provider(monkeypatch, data=None, error=None):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return json.dumps(data).encode()

    class Opener:
        def open(self, request, timeout):
            assert json.loads(request.data)['think'] is False
            if error:
                raise error
            return Response()

    monkeypatch.setattr(providers.urllib.request, 'build_opener', lambda *args: Opener())
    return providers.OllamaProvider('qwen3.5:27b', time.monotonic() + 30)


def message(**kwargs):
    return dict(done=True, done_reason='stop', message={'content': '{}'}, **kwargs)


@pytest.mark.parametrize('native,expected,status', [
    ({'prompt_eval_count': 12, 'eval_count': 0}, (12, 0), 'known'),
    ({'prompt_eval_count': 0, 'eval_count': 0}, (0, 0), 'known'),
    ({'prompt_eval_count': 12, 'eval_count': 5}, (12, 5), 'known'),
    ({}, (None, None), 'unknown'),
    ({'prompt_eval_count': None, 'eval_count': None}, (None, None), 'unknown'),
    ({'prompt_eval_count': 12}, (12, None), 'partial'),
    ({'eval_count': 0}, (None, 0), 'partial'),
])
def test_native_usage_states_reach_budget_events(tmp_path, monkeypatch, native, expected, status):
    inner = provider(monkeypatch, message(**native))
    events = Events(tmp_path / 'trace.jsonl', 'test')
    llm = BudgetLLM(inner, RunConfig(), events)
    llm.chat([{'role': 'user', 'content': 'test'}])
    metrics = llm.metrics()
    assert (metrics['prompt_tokens'], metrics['completion_tokens']) == expected
    assert metrics['usage_status'] == status
    assert metrics['cloud_api_cost_usd'] == 0 and metrics['local_compute_cost_usd'] is None
    finished = next(row for row in (json.loads(line) for line in events.path.read_text().splitlines())
                    if row['event'] == 'llm_finished')
    assert (finished['prompt_tokens'], finished['completion_tokens']) == expected
    assert finished['usage_known'] == (status == 'known')
    if status == 'known':
        assert metrics['budget_accounted_tokens'] == sum(expected)
    else:
        assert metrics['budget_accounted_tokens'] >= sum(value or 0 for value in expected)


def test_truncated_response_usage_is_kept_without_returning_candidate(tmp_path, monkeypatch):
    data = message(prompt_eval_count=40, eval_count=60)
    data['done_reason'] = 'length'
    inner = provider(monkeypatch, data)
    llm = BudgetLLM(inner, RunConfig(), Events(tmp_path / 'trace.jsonl', 'test'))
    with pytest.raises(providers.ProviderFailure, match='incomplete_model_response'):
        llm.chat([])
    assert llm.metrics()['prompt_tokens'] == 40 and llm.metrics()['completion_tokens'] == 60
    assert llm.metrics()['budget_accounted_tokens'] == 100
    assert llm.metrics()['failed_provider_attempt_usage'] == 'known'
    failed = json.loads((tmp_path / 'trace.jsonl').read_text().splitlines()[-1])
    assert failed['event'] == 'llm_failed' and failed['usage_known']
    assert inner.calls[0]['native_usage'] == {'prompt_eval_count': 40, 'eval_count': 60}


def test_transport_failure_has_unknown_usage_and_conservative_budget(tmp_path, monkeypatch):
    inner = provider(monkeypatch, error=TimeoutError('no response'))
    llm = BudgetLLM(inner, RunConfig(), Events(tmp_path / 'trace.jsonl', 'test'))
    with pytest.raises(providers.ProviderFailure):
        llm.chat([])
    assert llm.metrics()['prompt_tokens'] is None and llm.metrics()['completion_tokens'] is None
    assert llm.metrics()['budget_accounted_tokens'] > 0
    assert llm.metrics()['failed_calls'] == 1 and llm.metrics()['failed_provider_attempt_usage'] == 'unknown'


@pytest.mark.parametrize('value', [-1, True, '12'])
def test_invalid_counter_is_not_coerced_to_zero(tmp_path, monkeypatch, value):
    inner = provider(monkeypatch, message(prompt_eval_count=value, eval_count=5))
    llm = BudgetLLM(inner, RunConfig(), Events(tmp_path / 'trace.jsonl', 'test'))
    with pytest.raises(providers.ProviderFailure):
        llm.chat([])
    assert llm.metrics()['prompt_tokens'] is None
    assert llm.metrics()['completion_tokens'] == 5


def test_failed_local_generation_exports_reported_usage_without_error_text(tmp_path, monkeypatch):
    monkeypatch.setenv('CORECODER_LANGFUSE_ENABLED', '1')
    monkeypatch.delenv('CORECODER_LANGFUSE_ENV_FILE', raising=False)
    for key, value in {'LANGFUSE_PUBLIC_KEY': 'pk-test', 'LANGFUSE_SECRET_KEY': 'sk-test',
                       'LANGFUSE_BASE_URL': 'http://localhost:3300'}.items():
        monkeypatch.setenv(key, value)
    observer = Telemetry(tmp_path, TASK, 'ollama', 'qwen3.5:27b', factory=Client)
    observer.event('llm_started', {'call_id': 'llm-1', 'request_estimate': 100})
    observer.event('llm_failed', {'call_id': 'llm-1', 'error': 'private provider body',
        'usage_known': True, 'usage_status': 'known', 'usage_source': 'ollama_response',
        'prompt_tokens': 40, 'completion_tokens': 0})
    span = observer.client.root.children[0]
    assert span.values['as_type'] == 'generation' and span.values['level'] == 'ERROR'
    assert span.values['usage_details'] == {'input': 40, 'output': 0}
    assert span.values['cost_details'] == {'input': 0.0, 'output': 0.0}
    assert 'private provider body' not in json.dumps(span.values)
    observer.finish({'fresh_model_calls': 1, 'public_checks_passed': False})


def test_receipt_cannot_accept_mismatched_server_or_native_counts():
    report = {'provider_calls': [{'prompt_tokens': 12, 'completion_tokens': 0,
        'native_usage': {'prompt_eval_count': 12, 'eval_count': 0}}], 'fresh_model_calls': 1,
        'metrics': {'prompt_tokens': 12, 'completion_tokens': 0, 'cloud_api_cost_usd': 0, 'local_compute_cost_usd': None},
        'observability': {'trace_id': 'trace'}, 'status': 'public_checks_passed', 'public_checks_passed': True, 'thinking': False}
    events = [{'event': 'llm_finished', 'call_id': 'llm-1', 'usage_status': 'known', 'prompt_tokens': 12, 'completion_tokens': 0}]
    row = {'type': 'GENERATION', 'name': 'model-call', 'traceId': 'trace', 'endTime': 'finished', 'usageDetails': {'input': 12, 'output': 0},
        'metadata': {'call_id': 'llm-1', 'usage_status': 'known', 'cost_scope': 'cloud_api_fee'}, 'totalCost': 0}
    assert compare(report, events, [row])['native_local_server_match']
    row['usageDetails']['input'] = 13
    assert compare(report, events, [row]) is None
    row['usageDetails']['input'] = 12
    report['provider_calls'][0]['native_usage']['eval_count'] = None
    assert compare(report, events, [row]) is None
