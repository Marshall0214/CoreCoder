"""Native local thinking adapter; count all generated usage before validating output."""
import hashlib
import json
import urllib.request

from corecoder.llm import LLMResponse
from docs.experiments import provider_compare_worker_v1 as existing
from docs.experiments import thinking_calibration_v1 as calibration
from evals.runtime import BudgetLLM

PROVIDERS = {name: {'model': calibration.MODEL, 'base_url': 'http://localhost:11434',
                    'thinking': name == 'on'} for name in ('off', 'on')}


def identity():
    return calibration.identity(PROVIDERS['off']['base_url'])


class Provider:
    def __init__(self, policy, events, transport=None):
        self.settings = PROVIDERS[policy]
        self.model, self.events, self.calls = self.settings['model'], events, []
        self.transport = transport or self.send

    def send(self, request):
        req = urllib.request.Request(self.settings['base_url'] + '/api/chat',
                                     json.dumps(request).encode(), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=240) as response:
            return json.load(response)

    def chat(self, messages, tools=None, max_tokens=8192):
        if tools:
            raise ValueError('Structured repair has no model tools')
        request = {'model': self.model, 'messages': messages, 'think': self.settings['thinking'], 'stream': False,
                   'options': {'temperature': 0, 'top_p': 1, 'num_ctx': 16000,
                               'num_predict': max_tokens, 'seed': 17}}
        root = self.events.path.parent / f'provider-call-{len(self.calls) + 1:02d}'
        root.mkdir(exist_ok=False)
        (root / 'request.json').write_text(json.dumps(self.events.clean(request), indent=2), encoding='utf-8')
        call = {'response_received': False,
                'prompt_hash': hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()}
        self.calls.append(call)
        try:
            response = self.transport(request)
        except Exception as exc:
            call['error_type'] = type(exc).__name__
            raise
        message = response.get('message', {})
        content = message.get('content') or ''
        call.update(response_received=True, model_returned=response.get('model'),
                    finish_reason=response.get('done_reason'), done=response.get('done'),
                    reasoning_present=bool(message.get('thinking')), reasoning_chars=len(message.get('thinking') or ''),
                    prompt_tokens=response.get('prompt_eval_count'), completion_tokens=response.get('eval_count'),
                    tool_calls_present=bool(message.get('tool_calls')), total_duration_ns=response.get('total_duration'),
                    effective_output_limit=max_tokens)
        call['total_tokens'] = (call['prompt_tokens'] or 0) + (call['completion_tokens'] or 0)
        (root / 'response.txt').write_text(self.events.clean(content), encoding='utf-8')
        # Do not persist chain-of-thought; only length and presence telemetry.
        self.events.emit('native_response', **call)
        return LLMResponse(content=content, prompt_tokens=call['prompt_tokens'] or 0,
                           completion_tokens=call['completion_tokens'] or 0)

    def close(self):
        pass


class CheckedBudgetLLM(BudgetLLM):
    def chat(self, messages, tools=None, **kwargs):
        response = super().chat(messages, tools=tools, **kwargs)
        call = self.inner.calls[-1]
        error = None
        if not call['done'] or call['finish_reason'] != 'stop':
            error = 'output_truncated' if call['finish_reason'] == 'length' else 'unexpected_finish_reason'
        elif call['model_returned'] != self.inner.model:
            error = 'model_identity_mismatch'
        elif call['tool_calls_present']:
            error = 'unexpected_tool_call'
        elif not call['prompt_tokens'] or not call['completion_tokens']:
            error = 'missing_usage'
        elif not self.inner.settings['thinking'] and call['reasoning_present']:
            error = 'unexpected_thinking'
        elif not response.content.strip():
            error = 'empty_final_answer'
        if error:
            raise existing.InvalidCompletion(error)
        return response
