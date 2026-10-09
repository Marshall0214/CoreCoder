from dataclasses import replace
from types import SimpleNamespace

import pytest

from docs.experiments import deepseek_reasoning_provider_v1 as adapter
from docs.experiments import frozen_feedback_v1 as guarded
from evals.runtime import Events


def llm(tmp_path, finish='stop', total=700):
    requests = []

    def create(**request):
        requests.append(request)
        message = SimpleNamespace(content='{}', reasoning_content='private thoughts', tool_calls=[])
        usage = SimpleNamespace(prompt_tokens=200, completion_tokens=500, total_tokens=total,
                                completion_tokens_details=SimpleNamespace(reasoning_tokens=400))
        return SimpleNamespace(model='deepseek-flash', system_fingerprint='test', usage=usage,
                               choices=[SimpleNamespace(message=message, finish_reason=finish)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    events = Events(tmp_path / 'trace.jsonl', 'deepseek-low')
    inner = adapter.Provider('deepseek-low', events, client)
    config = replace(guarded.previous.repair.config(), max_output_tokens=8192,
                     output_policy='remaining', token_budget=1200)
    return adapter.CheckedBudgetLLM(inner, config, events), requests


def test_reasoning_usage_included_and_not_persisted(tmp_path):
    wrapped, requests = llm(tmp_path)
    wrapped.chat([{'role': 'user', 'content': 'repair with JSON'}])
    assert wrapped.spent == 700  # Reasoning 400 is included in completion 500, not charged twice.
    assert requests[0]['reasoning_effort'] == 'low'
    assert requests[0]['response_format'] == {'type': 'json_object'}
    assert 0 < requests[0]['max_tokens'] < 1200
    assert all('private thoughts' not in p.read_text() for p in tmp_path.rglob('*') if p.is_file())


@pytest.mark.parametrize('finish,total,error', [('length', 700, 'output_truncated'),
                                               ('stop', 900, 'usage_mismatch')])
def test_invalid_cloud_result_is_charged(tmp_path, finish, total, error):
    wrapped, _ = llm(tmp_path, finish, total)
    with pytest.raises(adapter.existing.InvalidCompletion, match=error):
        wrapped.chat([{'role': 'user', 'content': 'repair with JSON'}])
    assert wrapped.spent == 700
