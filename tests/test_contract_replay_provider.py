import json
from types import SimpleNamespace

import pytest

from docs.experiments import contract_replay_provider_v1 as replay
from docs.experiments.public_contract_repair_v1 import trial_config
from evals.runtime import Events


@pytest.mark.parametrize('changed', [False, True])
def test_replay_requires_identical_request_and_charges_historical_tokens(tmp_path, monkeypatch, changed):
    seed = tmp_path / 'seed'
    seed.mkdir()
    messages = [{'role': 'user', 'content': 'original'}]
    (seed / 'initial-messages.json').write_text(json.dumps(messages))
    (seed / 'initial-response.txt').write_text('{"edits": []}')
    call = dict(finish_reason='stop', model_returned='deepseek-flash', effective_output_limit=32768,
                prompt_tokens=100, completion_tokens=200, total_tokens=300, tool_calls_present=False)
    (seed / 'worker-result.json').write_text(json.dumps({'initial': {'status': 'completed'}, 'provider_calls': [call]}))
    monkeypatch.setattr(replay, 'SEED', seed)
    root = tmp_path / 'run'
    root.mkdir()
    provider = replay.Provider('deepseek-high', Events(root / 'trace.jsonl', 'test'), client=SimpleNamespace())
    llm = replay.CheckedBudgetLLM(provider, trial_config('deepseek-high'), provider.events)
    if changed:
        with pytest.raises(ValueError, match='identical initial request'):
            llm.chat([{'role': 'user', 'content': 'different'}], tools=[])
        assert provider.calls == []
    else:
        response = llm.chat(messages, tools=[])
        assert response.content == '{"edits": []}'
        assert provider.calls[0]['replayed']
        assert llm.metrics()['budget_accounted_tokens'] == 300
        assert llm.metrics()['llm_calls'] == 1
