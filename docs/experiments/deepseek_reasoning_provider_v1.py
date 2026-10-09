"""Configured Flash low-effort reasoning with JSON output and accounted usage."""
import hashlib
import json
import os

from openai import OpenAI

from corecoder.llm import LLMResponse
from docs.experiments import provider_compare_worker_v1 as existing
from evals.runtime import BudgetLLM

PROVIDERS = {'deepseek-low': {'model': 'deepseek-flash', 'base_url': 'https://api.deepseek.com',
                             'thinking': True, 'reasoning_effort': 'low'}}


def identity():
    existing.deepseek_key()
    return {'model_alias': 'deepseek-flash', 'cloud_weight_digest': None,
            'limits': 'Provider alias may change; fingerprint recorded per response'}


class Provider:
    def __init__(self, policy, events, client=None):
        self.settings = PROVIDERS[policy]
        self.model, self.events, self.calls = self.settings['model'], events, []
        if client is None:
            key = existing.deepseek_key()
            os.environ['DEEPSEEK_API_KEY'] = key
            client = OpenAI(api_key=key, base_url=self.settings['base_url'], timeout=240, max_retries=0)
        self.client = client

    def chat(self, messages, tools=None, max_tokens=8192):
        if tools:
            raise ValueError('Structured repair has no model tools')
        request = {'model': self.model, 'messages': messages, 'stream': False,
                   'max_tokens': max_tokens, 'reasoning_effort': 'low', 'top_p': 0.95,
                   'extra_body': {'thinking': {'type': 'enabled'}},
                   'response_format': {'type': 'json_object'}}
        root = self.events.path.parent / f'provider-call-{len(self.calls) + 1:02d}'
        root.mkdir(exist_ok=False)
        (root / 'request.json').write_text(json.dumps(self.events.clean(request), indent=2), encoding='utf-8')
        call = {'response_received': False, 'effective_output_limit': max_tokens,
                'prompt_hash': hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()}
        self.calls.append(call)
        try:
            response = self.client.chat.completions.create(**request)
        except Exception as exc:
            call.update(error_type=type(exc).__name__, http_status=getattr(exc, 'status_code', None))
            raise
        choice, usage = response.choices[0], response.usage
        reasoning = getattr(choice.message, 'reasoning_content', None) or ''
        details = getattr(usage, 'completion_tokens_details', None)
        content = choice.message.content or ''
        call.update(response_received=True, model_returned=response.model, finish_reason=choice.finish_reason,
                    reasoning_present=bool(reasoning), reasoning_chars=len(reasoning),
                    reasoning_tokens=getattr(details, 'reasoning_tokens', None),
                    prompt_tokens=getattr(usage, 'prompt_tokens', None),
                    completion_tokens=getattr(usage, 'completion_tokens', None),
                    total_tokens=getattr(usage, 'total_tokens', None),
                    system_fingerprint=getattr(response, 'system_fingerprint', None),
                    tool_calls_present=bool(choice.message.tool_calls))
        (root / 'response.txt').write_text(self.events.clean(content), encoding='utf-8')
        self.events.emit('deepseek_reasoning_response', **call)
        return LLMResponse(content=content, prompt_tokens=call['prompt_tokens'] or 0,
                           completion_tokens=call['completion_tokens'] or 0)

    def close(self):
        self.client.close()


class CheckedBudgetLLM(BudgetLLM):
    def chat(self, messages, tools=None, **kwargs):
        response = super().chat(messages, tools=tools, **kwargs)
        call = self.inner.calls[-1]
        error = None
        if call['finish_reason'] != 'stop':
            error = 'output_truncated' if call['finish_reason'] == 'length' else 'unexpected_finish_reason'
        elif call['model_returned'] != self.inner.model:
            error = 'model_identity_mismatch'
        elif call['tool_calls_present']:
            error = 'unexpected_tool_call'
        elif not call['prompt_tokens'] or not call['completion_tokens']:
            error = 'missing_usage'
        elif call['total_tokens'] != call['prompt_tokens'] + call['completion_tokens']:
            error = 'usage_mismatch'
        elif not response.content.strip():
            error = 'empty_final_answer'
        if error:
            raise existing.InvalidCompletion(error)
        return response
