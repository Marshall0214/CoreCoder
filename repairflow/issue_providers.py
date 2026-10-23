"""Explicit scripted responses or loopback-only Ollama; no cloud credentials."""
import json
import time
import urllib.request

from corecoder.llm import LLMResponse
from repairflow.github_issue import NoRedirect


class ProviderFailure(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(status)


class ScriptedProvider:
    """Exercise execution with supplied answers, never claim model performance."""
    model = 'scripted-not-a-model'

    def __init__(self, path):
        with path.open('rb') as stream:
            raw = stream.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Scripted responses exceed size limit')
        self.responses = json.loads(raw)
        if (not isinstance(self.responses, list) or not 1 <= len(self.responses) <= 100
                or not all(isinstance(row, str) for row in self.responses)):
            raise ValueError('Require 1 to 100 JSON response strings')
        self.calls = []

    def chat(self, messages, tools=None, **kwargs):
        if len(self.calls) >= len(self.responses):
            raise ProviderFailure('scripted_responses_exhausted')
        content = self.responses[len(self.calls)]
        self.calls.append({'scripted': True, 'usage_known': False})
        return LLMResponse(content=content)  # Unknown usage; BudgetLLM reserves conservatively.


class OllamaProvider:
    """Native API explicitly disables thinking. Never loads .env or cloud keys."""
    def __init__(self, model, deadline):
        if (not isinstance(model, str) or not model or len(model) > 128
                or any(c.isspace() for c in model) or any(c in model for c in '/\\@')
                or 'cloud' in model.lower()):
            raise ValueError('Require an installed local Ollama model name; cloud models are disabled')
        self.model, self.deadline, self.calls = model, deadline, []

    def chat(self, messages, tools=None, max_tokens=32768):
        if tools:
            raise ValueError('Prepared Issue repair accepts structured patches, not tool requests')
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ProviderFailure('task_timeout')
        payload = {'model': self.model, 'messages': messages, 'stream': False, 'think': False,
                   'format': 'json', 'options': {'temperature': 0, 'num_predict': max_tokens, 'num_ctx': 65536}}
        record = {'scripted': False, 'thinking_requested': False}
        self.calls.append(record)
        request = urllib.request.Request('http://127.0.0.1:11434/api/chat',
                                         json.dumps(payload).encode(), {'Content-Type': 'application/json'})
        try:
            # Ignore proxy environment variables and refuse redirects off the loopback endpoint.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(request, timeout=min(480, remaining)) as response:
                raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ProviderFailure('provider_response_limit')
            data = json.loads(raw)
            message = data['message']
            record.update(finish_reason=data.get('done_reason'), model_returned=data.get('model'))
            if data.get('done') is not True or data.get('done_reason') != 'stop':
                raise ProviderFailure('incomplete_model_response')
            if message.get('thinking') or message.get('tool_calls'):
                raise ProviderFailure('unexpected_model_response')
            content = message['content']
            if not isinstance(content, str):
                raise TypeError('Invalid response content')
            usage = [data.get(key, 0) for key in ('prompt_eval_count', 'eval_count')]
            if any(type(value) is not int or value < 0 for value in usage):
                raise ValueError('Invalid usage counts')
            record.update(prompt_tokens=usage[0], completion_tokens=usage[1])
            return LLMResponse(content=content, prompt_tokens=usage[0], completion_tokens=usage[1])
        except ProviderFailure as exc:
            record['failure'] = exc.status
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            record['failure'] = 'local_provider_failed'
            raise ProviderFailure('local_provider_failed') from exc
