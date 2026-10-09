from dataclasses import replace

import pytest

from docs.experiments import frozen_feedback_v1 as guarded
from docs.experiments import reasoning_provider_v1 as adapter
from docs.experiments import reasoning_provider_v2 as sampled
from evals.runtime import Events


def setup_llm(tmp_path, policy, module=adapter, **changes):
    result = {'model': adapter.calibration.MODEL, 'done': True, 'done_reason': 'stop',
              'prompt_eval_count': 100, 'eval_count': 400,
              'message': {'content': '{}', 'thinking': 'private reasoning' if policy == 'on' else ''}}
    result.update(changes)
    requests = []

    def transport(request):
        requests.append(request)
        return result

    events = Events(tmp_path / 'trace.jsonl', policy)
    provider = module.Provider(policy, events, transport)
    config = replace(guarded.previous.repair.config(), max_output_tokens=8192,
                     output_policy='remaining', token_budget=1200)
    return module.CheckedBudgetLLM(provider, config, events), requests


@pytest.mark.parametrize('policy', ['off', 'on'])
@pytest.mark.parametrize('module', [adapter, sampled])
def test_budget_bounds_native_generation_and_charges_thinking(tmp_path, policy, module):
    llm, requests = setup_llm(tmp_path, policy, module)
    llm.chat([{'role': 'user', 'content': 'repair'}], tools=[])
    assert requests[0]['think'] is (policy == 'on')
    assert 0 < requests[0]['options']['num_predict'] < 1200
    assert llm.metrics()['budget_accounted_tokens'] == 500
    if module is sampled:
        assert requests[0]['options']['temperature'] == 0.6
        assert requests[0]['options']['repeat_penalty'] == 1.0
    assert all('private reasoning' not in p.read_text() for p in tmp_path.rglob('*') if p.is_file())


@pytest.mark.parametrize('changes,error', [
    ({'done_reason': 'length'}, 'output_truncated'),
    ({'message': {'content': '', 'thinking': 'reasoning'}}, 'empty_final_answer'),
    ({'model': 'other'}, 'model_identity_mismatch'),
    ({'message': {'content': '{}', 'tool_calls': [{}]}}, 'unexpected_tool_call'),
])
@pytest.mark.parametrize('module', [adapter, sampled])
def test_unusable_response_is_charged_before_rejection(tmp_path, changes, error, module):
    llm, _ = setup_llm(tmp_path, 'on', module, **changes)
    with pytest.raises(adapter.existing.InvalidCompletion, match=error):
        llm.chat([{'role': 'user', 'content': 'repair'}])
    assert llm.metrics()['budget_accounted_tokens'] == 500
