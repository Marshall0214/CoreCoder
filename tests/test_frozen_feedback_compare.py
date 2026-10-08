from types import SimpleNamespace

import pytest

from corecoder.llm import LLMResponse
from docs.experiments import frozen_feedback_compare_v1 as comparison
from evals.runtime import Events
from evals.schema import RunConfig


class Provider:
    model = 'qwen3.5:27b'

    def __init__(self, finish='stop'):
        self.calls = []
        self.finish = finish

    def chat(self, messages, tools=None):
        self.calls.append({'finish_reason': self.finish, 'reasoning_present': False,
                           'reasoning_tokens': 0, 'model_returned': self.model})
        return LLMResponse(content='patch', tool_calls=[], prompt_tokens=30, completion_tokens=10)


@pytest.mark.parametrize('finish', ['stop', 'length'])
def test_shared_first_response_charges_both_arm_budgets(tmp_path, finish):
    shared = comparison.SharedInitial()
    providers = [Provider(finish), Provider(finish)]
    for i, provider in enumerate(providers):
        llm = comparison.previous.CheckedBudgetLLM(comparison.PairedProvider(provider, shared),
                                                  RunConfig(token_budget=15000, max_output_tokens=2048),
                                                  Events(tmp_path / f'{i}.jsonl', 'test'))
        if finish == 'length':
            with pytest.raises(comparison.previous.baseline.InvalidCompletion, match='output_truncated'):
                llm.chat([{'role': 'user', 'content': 'identical'}], tools=[])
        else:
            assert llm.chat([{'role': 'user', 'content': 'identical'}], tools=[]).content == 'patch'
        assert llm.metrics()['budget_accounted_tokens'] == 40
        assert llm.metrics()['llm_calls'] == 1
    assert providers[1].calls[0]['shared_initial_replay']
    assert not providers[0].calls[0].get('shared_initial_replay')


def test_changed_initial_prompt_is_rejected():
    shared = comparison.SharedInitial()
    shared.chat(Provider(), [{'role': 'user', 'content': 'one'}], [])
    with pytest.raises(ValueError, match='requests differ'):
        shared.chat(Provider(), [{'role': 'user', 'content': 'two'}], [])


def test_correction_is_new_inference_not_shared_cache():
    shared = comparison.SharedInitial()
    first = comparison.PairedProvider(Provider(), shared)
    second = comparison.PairedProvider(Provider(), shared)
    first.chat(['initial'], [])
    second.chat(['initial'], [])
    first.chat(['old feedback'], [])
    second.chat(['new feedback'], [])
    assert len(first.calls) == len(second.calls) == 2
    assert not second.calls[1].get('shared_initial_replay')


def test_initial_transport_failure_is_not_retried_in_second_arm():
    shared = comparison.SharedInitial()
    provider = SimpleNamespace(calls=[{'response_received': False}], chat=lambda *a: (_ for _ in ()).throw(OSError('secret')))
    with pytest.raises(OSError):
        shared.chat(provider, ['initial'], [])
    other = Provider()
    with pytest.raises(RuntimeError, match='OSError') as exc:
        shared.chat(other, ['initial'], [])
    assert 'secret' not in str(exc.value)
    assert other.calls[0]['shared_initial_replay']
