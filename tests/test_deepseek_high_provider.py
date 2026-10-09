from dataclasses import replace
from types import SimpleNamespace

import pytest

from docs.experiments import deepseek_high_provider_v1 as adapter
from docs.experiments import frozen_feedback_v1 as guarded
from evals.runtime import Events


@pytest.mark.parametrize('finish', ['stop', 'length'])
def test_high_reasoning_request_accounts_all_completion_without_logging_thoughts(tmp_path, finish):
    requests = []

    def create(**request):
        requests.append(request)
        message = SimpleNamespace(content='{"edits":[]}', reasoning_content='private reasoning', tool_calls=[])
        usage = SimpleNamespace(prompt_tokens=200, completion_tokens=10000, total_tokens=10200,
                                completion_tokens_details=SimpleNamespace(reasoning_tokens=9900))
        return SimpleNamespace(model='deepseek-flash', system_fingerprint='test', usage=usage,
                               choices=[SimpleNamespace(message=message, finish_reason=finish)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    events = Events(tmp_path / 'trace.jsonl', 'deepseek-high')
    provider = adapter.Provider('deepseek-high', events, client)
    config = replace(guarded.previous.repair.config(), token_budget=60000, context_tokens=65536,
                     max_output_tokens=32768, output_policy='remaining')
    llm = adapter.CheckedBudgetLLM(provider, config, events)
    if finish == 'length':
        with pytest.raises(adapter.existing.InvalidCompletion, match='output_truncated'):
            llm.chat([{'role': 'user', 'content': 'Return JSON patch'}])
    else:
        llm.chat([{'role': 'user', 'content': 'Return JSON patch'}])
    assert llm.spent == 10200
    assert requests[0]['max_tokens'] == 32768
    assert requests[0]['reasoning_effort'] == 'high'
    assert requests[0]['extra_body'] == {'thinking': {'type': 'enabled'}}
    assert 'tools' not in requests[0]
    assert all('private reasoning' not in p.read_text() for p in tmp_path.rglob('*') if p.is_file())
