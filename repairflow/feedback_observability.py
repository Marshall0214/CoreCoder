"""Account for local feedback inference without changing its output contract."""
import time

from evals.context_policy import request_breakdown
from evals.local50_unmetered import LocalConfig
from evals.runtime import BudgetLLM
from repairflow.issue_providers import OllamaProvider


class ObservedFeedbackLLM(BudgetLLM):
    """Schema-preserving local calls; token estimates are observations, not gates."""

    def __init__(self, inner, events):
        if not isinstance(inner, OllamaProvider):
            raise TypeError('Feedback inference requires an explicit local Ollama provider')
        super().__init__(inner, LocalConfig(), events)

    def chat(self, messages, tools=None, *, response_schema=None, max_tokens=-1):
        if tools or not isinstance(response_schema, dict) or not response_schema:
            raise ValueError('Feedback requires a nonempty response schema and no native tools')
        if type(max_tokens) is not int or max_tokens != -1:
            raise ValueError('Feedback predictions must remain unlimited with max_tokens=-1')
        breakdown = request_breakdown(messages, tools, response_format=response_schema)
        self.events.emit('request_preflight', next_call=self.calls + 1, **breakdown,
                         token_budget=None, cumulative_enforced=False, context_preflight_enforced=False,
                         effective_max_output_tokens=None, provider_context_tokens=65536,
                         output_policy='account_only')
        self.calls += 1
        call_id, started = f'llm-{self.calls}', time.perf_counter()
        self.events.emit('llm_started', call_id=call_id, request_estimate=breakdown['request_estimate'],
                         message_count=len(messages))
        try:
            response = self.inner.chat(messages, tools=tools, response_schema=response_schema, max_tokens=max_tokens)
        except Exception as exc:
            usage = self._account_usage(exc, breakdown['request_estimate'], failed=True)
            self.events.emit('llm_failed', call_id=call_id, seconds=round(time.perf_counter() - started, 4),
                             error=f'{type(exc).__name__}: {exc}', **usage)
            raise
        usage = self._account_usage(response, breakdown['request_estimate'])
        self.events.emit('llm_finished', call_id=call_id, seconds=round(time.perf_counter() - started, 4),
                         tools=[call.name for call in response.tool_calls], **usage)
        return response

    def metrics(self):
        return {**super().metrics(), 'budget_enforcement': 'account_only; no token cutoffs',
                'token_budget': None, 'max_output_tokens': None, 'context_preflight_enforced': False,
                'provider_context_tokens': 65536,
                'known_tokens_minimum': self.prompt_known + self.completion_known}
