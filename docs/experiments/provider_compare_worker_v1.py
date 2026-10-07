"""Strict, non-thinking OpenAI-compatible adapters for a fresh provider comparison."""

import argparse
import hashlib
import json
import os
import time
from dataclasses import replace
from pathlib import Path

from dotenv import dotenv_values
from openai import OpenAI

from corecoder.llm import LLMResponse, ToolCall
from docs.experiments import unified_feedback_worker_v1 as unified
from evals.runtime import BudgetExceeded, BudgetLLM, Events

ROOT = Path(__file__).resolve().parents[2]
PROVIDERS = {
    'qwen': {'model': 'qwen3.5:27b', 'base_url': 'http://localhost:11434/v1', 'reasoning_effort': 'none'},
    'deepseek': {'model': 'deepseek-flash', 'base_url': 'https://api.deepseek.com',
                 'extra_body': {'thinking': {'type': 'disabled'}}},
}


def deepseek_key(root=ROOT):
    """Explicit provider key; never select generic OPENAI/CORECODER credentials."""
    value = dotenv_values(root / '.env').get('DEEPSEEK_API_KEY') or os.getenv('DEEPSEEK_API_KEY')
    if not value or not value.strip():
        raise ValueError('Configure DEEPSEEK_API_KEY in project .env or environment')
    return value.strip()


class InvalidCompletion(Exception):
    pass


class Provider:
    def __init__(self, name, events, key=None, client=None):
        if name not in PROVIDERS:
            raise ValueError('Unknown provider')
        self.name, self.settings, self.events = name, PROVIDERS[name], events
        self.model, self.calls = self.settings['model'], []
        if client is None:
            credential = key if name == 'deepseek' else 'ollama'
            if not credential:
                raise ValueError('Missing explicit provider credential')
            client = OpenAI(api_key=credential, base_url=self.settings['base_url'], timeout=60, max_retries=0)
        self.client = client

    def chat(self, messages, tools=None):
        if tools:
            raise ValueError('Tools are outside this structured patch protocol')
        request = {'model': self.model, 'messages': messages, 'stream': False, 'temperature': 0, 'top_p': 1, 'max_tokens': 2048}
        request.update({key: value for key, value in self.settings.items() if key in {'reasoning_effort', 'extra_body'}})
        number = len(self.calls) + 1
        root = self.events.path.parent / f'provider-call-{number:02d}'
        root.mkdir(exist_ok=False)
        (root / 'request.json').write_text(json.dumps(self.events.clean(request), indent=2), encoding='utf-8')
        started = time.perf_counter()
        call = {'provider': self.name, 'model_requested': self.model, 'request_sha256': hashlib.sha256(
            json.dumps(request, ensure_ascii=False).encode()).hexdigest(), 'prompt_hash': hashlib.sha256(
                json.dumps(messages, ensure_ascii=False).encode()).hexdigest(), 'response_received': False}
        self.calls.append(call)
        try:
            response = self.client.chat.completions.create(**request)
        except Exception as exc:
            call.update(error_type=type(exc).__name__, http_status=getattr(exc, 'status_code', None))
            raise
        finally:
            call['seconds'] = round(time.perf_counter() - started, 4)
        choice, usage = response.choices[0], response.usage
        reasoning = getattr(choice.message, 'reasoning_content', None) or getattr(choice.message, 'reasoning', None)
        details = getattr(usage, 'completion_tokens_details', None)
        call.update(response_received=True, model_returned=response.model, finish_reason=choice.finish_reason,
                    system_fingerprint=getattr(response, 'system_fingerprint', None), reasoning_present=bool(reasoning),
                    reasoning_tokens=getattr(details, 'reasoning_tokens', None),
                    prompt_tokens=getattr(usage, 'prompt_tokens', None), completion_tokens=getattr(usage, 'completion_tokens', None),
                    total_tokens=getattr(usage, 'total_tokens', None),
                    cache_hit_tokens=getattr(usage, 'prompt_cache_hit_tokens', None),
                    cache_miss_tokens=getattr(usage, 'prompt_cache_miss_tokens', None))
        content = choice.message.content or ''
        (root / 'response.txt').write_text(self.events.clean(content), encoding='utf-8')
        self.events.emit('provider_response', **call)
        tools_out = []
        for tool in choice.message.tool_calls or []:
            try:
                arguments = json.loads(tool.function.arguments)
            except (TypeError, ValueError):
                arguments = {}
            tools_out.append(ToolCall(tool.id, tool.function.name, arguments))
        return LLMResponse(content=content, tool_calls=tools_out,
                           prompt_tokens=call['prompt_tokens'] or 0, completion_tokens=call['completion_tokens'] or 0)


class CheckedBudgetLLM(BudgetLLM):
    def chat(self, messages, tools=None, **kwargs):
        # Charge returned usage before refusing unusable output; never treat it as free.
        response = super().chat(messages, tools=tools, **kwargs)
        call = self.inner.calls[-1]
        if call['reasoning_present'] or (call['reasoning_tokens'] or 0) > 0:
            raise InvalidCompletion('unexpected_thinking')
        if call['finish_reason'] != 'stop':
            raise InvalidCompletion('output_truncated' if call['finish_reason'] == 'length' else 'unexpected_finish_reason')
        if not response.content.strip():
            raise InvalidCompletion('empty_final_answer')
        if call['model_returned'] != self.inner.model:
            raise InvalidCompletion('model_identity_mismatch')
        return response


def worker(path):
    job = json.loads(path.read_text(encoding='utf-8'))
    key = deepseek_key() if job['provider'] == 'deepseek' else None
    if key:
        os.environ['DEEPSEEK_API_KEY'] = key  # Make the existing event redactor aware of this credential.
    events = Events(path.parent / 'trace.jsonl', job['provider'])
    result, provider, llm = {'status': 'agent_error'}, None, None
    try:
        config = unified.repair.config()
        unified.repair.check_identity(config)
        config = replace(config, model=PROVIDERS[job['provider']]['model'], base_url=PROVIDERS[job['provider']]['base_url'])
        provider = Provider(job['provider'], events, key)
        llm = CheckedBudgetLLM(provider, config, events)
        unified.run_candidate(llm, job, events, result)
        unified.repair.check_identity(unified.repair.config())
    except InvalidCompletion as exc:
        result.update(status=str(exc))
    except BudgetExceeded as exc:
        result.update(status='budget_exceeded', error=str(exc))
    except Exception as exc:  # noqa: BLE001 - capture failures without printing credentials
        result.update(status='agent_error', error_type=type(exc).__name__, http_status=getattr(exc, 'status_code', None))
    finally:
        result.update(metrics=llm.metrics() if llm else None, provider_calls=provider.calls if provider else [])
        if provider and provider.calls and not result.get('prompt_hash'):
            result['prompt_hash'] = provider.calls[0]['prompt_hash']
        (path.parent / 'worker-result.json').write_text(json.dumps(events.clean(result), indent=2), encoding='utf-8')
        if provider:
            provider.client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    worker(parser.parse_args().worker.resolve())
