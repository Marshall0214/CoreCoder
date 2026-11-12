"""The feedback observer forwards schemas and retains measured/unknown usage."""
import copy
import json
import time

import pytest

from evals.runtime import Events
from repairflow.feedback_observability import ObservedFeedbackLLM
from repairflow.issue_providers import OllamaProvider, ProviderFailure, UsageResponse

SCHEMA = {'type': 'object', 'properties': {'action': {'const': 'finish'}}, 'required': ['action']}
MESSAGES = [{'role': 'user', 'content': 'Inspect the current candidate.'}]


class LocalReplies(OllamaProvider):
    def __init__(self, reply):
        super().__init__('qwen3.5:27b', time.monotonic() + 60)
        self.reply, self.requests = reply, []

    def chat(self, messages, tools=None, *, response_schema=None, max_tokens=-1):
        self.requests.append(copy.deepcopy({'messages': messages, 'tools': tools,
                                           'response_schema': response_schema, 'max_tokens': max_tokens}))
        self.calls.append({'native_usage': getattr(self.reply, 'reported_usage', {})})
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def observed(tmp_path, reply):
    provider = LocalReplies(reply)
    events = Events(tmp_path / 'trace.jsonl', 'feedback-observer')
    return ObservedFeedbackLLM(provider, events), provider


def events(tmp_path):
    return [json.loads(line) for line in (tmp_path / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]


def test_schema_and_unlimited_output_are_forwarded_unchanged(tmp_path):
    response = UsageResponse(content='{"action":"finish"}',
                             reported_usage={'prompt_tokens': 42, 'completion_tokens': 8})
    llm, provider = observed(tmp_path, response)
    assert llm.chat(MESSAGES, tools=[], response_schema=SCHEMA, max_tokens=-1) is response
    assert provider.requests == [{'messages': MESSAGES, 'tools': [], 'response_schema': SCHEMA, 'max_tokens': -1}]
    assert llm.calls == len(provider.calls) == 1
    rows = events(tmp_path)
    assert [row['event'] for row in rows] == ['request_preflight', 'llm_started', 'llm_finished']
    assert rows[0]['response_format_estimate'] > 0
    assert rows[0]['next_call'] == 1 and rows[0]['cumulative_enforced'] is False
    assert rows[2]['prompt_tokens'] == 42 and rows[2]['completion_tokens'] == 8
    assert rows[2]['seconds'] >= 0


def test_large_context_and_usage_never_trigger_token_stop(tmp_path):
    response = UsageResponse(content='{}', reported_usage={'prompt_tokens': 90000, 'completion_tokens': 10000})
    llm, provider = observed(tmp_path, response)
    messages = [{'role': 'user', 'content': 'large input ' * 30000}]
    for _ in range(3):
        llm.chat(messages, response_schema=SCHEMA)
    metrics = llm.metrics()
    assert metrics['llm_calls'] == len(provider.calls) == 3
    assert metrics['prompt_tokens'] == 270000 and metrics['completion_tokens'] == 30000
    assert metrics['token_budget'] is None and metrics['max_output_tokens'] is None
    assert metrics['known_tokens_minimum'] == 300000 and metrics['context_preflight_enforced'] is False
    rows = events(tmp_path)
    assert max(row.get('request_estimate', 0) for row in rows) > 65536
    assert 'budget_blocked' not in [row['event'] for row in rows]
    assert all(row['max_tokens'] == -1 for row in provider.requests)


def test_incomplete_provider_failure_retains_usage_and_is_not_retried(tmp_path):
    failure = ProviderFailure('incomplete_model_response', reported_usage={'prompt_tokens': 100, 'completion_tokens': 30})
    llm, provider = observed(tmp_path, failure)
    with pytest.raises(ProviderFailure) as caught:
        llm.chat(MESSAGES, response_schema=SCHEMA)
    assert caught.value is failure and llm.calls == len(provider.calls) == 1
    metrics = llm.metrics()
    assert metrics['failed_calls'] == 1 and metrics['prompt_tokens'] == 100
    assert metrics['completion_tokens'] == 30 and metrics['known_tokens_minimum'] == 130
    row = events(tmp_path)[-1]
    assert row['event'] == 'llm_failed' and row['usage_known'] is True
    assert row['seconds'] >= 0 and row['prompt_tokens'] == 100


def test_missing_usage_stays_unknown_instead_of_zero(tmp_path):
    llm, _ = observed(tmp_path, UsageResponse(content='{}'))
    llm.chat(MESSAGES, response_schema=SCHEMA)
    metrics = llm.metrics()
    assert metrics['usage_status'] == 'unknown'
    assert metrics['prompt_tokens'] is None and metrics['completion_tokens'] is None
    assert metrics['missing_usage_calls'] == 1 and metrics['known_tokens_minimum'] == 0
    assert events(tmp_path)[-1]['prompt_tokens'] is None


def test_partial_failure_and_success_keep_measured_lower_bound(tmp_path):
    llm, provider = observed(tmp_path, ProviderFailure('local_provider_failed', reported_usage={'prompt_tokens': 100}))
    with pytest.raises(ProviderFailure):
        llm.chat(MESSAGES, response_schema=SCHEMA)
    provider.reply = UsageResponse(content='{}', reported_usage={'prompt_tokens': 7, 'completion_tokens': 3})
    llm.chat(MESSAGES, response_schema=SCHEMA)
    metrics = llm.metrics()
    assert metrics['llm_calls'] == 2 and metrics['prompt_tokens'] == 107
    assert metrics['completion_tokens'] is None and metrics['known_completion_tokens'] == 3
    assert metrics['known_tokens_minimum'] == 110 and metrics['missing_usage_calls'] == 1
    assert metrics['usage_status'] == 'partial'


def test_measured_zero_usage_is_known(tmp_path):
    llm, _ = observed(tmp_path, UsageResponse(content='{}', reported_usage={'prompt_tokens': 0, 'completion_tokens': 0}))
    llm.chat(MESSAGES, response_schema=SCHEMA)
    assert llm.metrics()['usage_status'] == 'known'
    assert llm.metrics()['prompt_tokens'] == llm.metrics()['completion_tokens'] == 0


@pytest.mark.parametrize('kwargs', [
    {'response_schema': None}, {'response_schema': {}}, {'response_schema': []},
    {'response_schema': SCHEMA, 'tools': [{'type': 'function'}]},
    {'response_schema': SCHEMA, 'max_tokens': 2048}, {'response_schema': SCHEMA, 'max_tokens': -1.0},
])
def test_invalid_contract_is_rejected_before_counting_or_calling(tmp_path, kwargs):
    llm, provider = observed(tmp_path, UsageResponse(content='{}'))
    with pytest.raises(ValueError):
        llm.chat(MESSAGES, **kwargs)
    assert llm.calls == 0 and provider.requests == provider.calls == []
    assert not (tmp_path / 'trace.jsonl').exists()


def test_nonlocal_provider_and_configuration_override_are_rejected(tmp_path):
    with pytest.raises(TypeError, match='local Ollama'):
        ObservedFeedbackLLM(object(), Events(tmp_path / 'trace.jsonl', 'bad'))
    llm, provider = observed(tmp_path, UsageResponse(content='{}'))
    with pytest.raises(TypeError):
        llm.chat(MESSAGES, response_schema=SCHEMA, response_format='json')
    with pytest.raises(TypeError):
        ObservedFeedbackLLM(provider, llm.events, config=object())
    assert llm.calls == 0 and provider.requests == provider.calls == []
