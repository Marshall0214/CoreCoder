from dataclasses import replace
from types import SimpleNamespace

import pytest

from docs.experiments import deepseek_direct_provider_v1 as adapter
from docs.experiments import frozen_feedback_v1 as guarded
from evals.runtime import Events


@pytest.mark.parametrize('reasoning', ['', 'unexpected private reasoning'])
def test_direct_mode_accounts_usage_and_rejects_thinking(tmp_path, reasoning):
    requests = []

    def create(**request):
        requests.append(request)
        message = SimpleNamespace(content='{}', reasoning_content=reasoning, tool_calls=[])
        usage = SimpleNamespace(prompt_tokens=200, completion_tokens=500, total_tokens=700,
                                completion_tokens_details=None)
        return SimpleNamespace(model='deepseek-flash', system_fingerprint=None, usage=usage,
                               choices=[SimpleNamespace(message=message, finish_reason='stop')])

    events = Events(tmp_path / 'trace.jsonl', 'deepseek-off')
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    provider = adapter.Provider('deepseek-off', events, client)
    config = replace(guarded.previous.repair.config(), max_output_tokens=8192,
                     output_policy='remaining', token_budget=1200)
    llm = adapter.CheckedBudgetLLM(provider, config, events)
    if reasoning:
        with pytest.raises(adapter.existing.InvalidCompletion, match='unexpected_thinking'):
            llm.chat([{'role': 'user', 'content': 'JSON repair'}])
    else:
        llm.chat([{'role': 'user', 'content': 'JSON repair'}])
    assert llm.spent == 700
    assert requests[0]['reasoning_effort'] == 'none'
    assert requests[0]['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert 0 < requests[0]['max_tokens'] < 1200
    assert all('unexpected private reasoning' not in p.read_text() for p in tmp_path.rglob('*') if p.is_file())
