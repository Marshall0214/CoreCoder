"""Native Ollama thinking-toggle probe; no grading material or reference edits."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

from corecoder.llm import LLMResponse
from evals.fixed_evidence import SYSTEM, apply_patch_json
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.schema import RunConfig


class NativeLLM:
    def __init__(self, job, events):
        self.job, self.events, self.model = job, events, job['model']
        self.telemetry = {'response_received': False}

    def chat(self, messages, tools=None):
        if tools:
            raise ValueError('Tools are not part of this calibration')
        request = {'model': self.model, 'messages': messages, 'think': self.job['thinking'], 'stream': False,
                   'options': {'temperature': 0, 'top_p': 0.95, 'num_ctx': 16000, 'num_predict': 2048, 'seed': 17}}
        (self.events.path.parent / 'request.json').write_text(json.dumps(request, indent=2), encoding='utf-8')
        req = urllib.request.Request(self.job['base_url'] + '/api/chat', json.dumps(request).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=120) as stream:
            response = json.load(stream)
        message = response.get('message', {})
        thinking, content = message.get('thinking', ''), message.get('content', '')
        self.telemetry = {'response_received': True, 'provider_model': response.get('model'),
            'thinking_present': bool(thinking), 'thinking_chars': len(thinking), 'content_chars': len(content),
            'tool_calls_present': bool(message.get('tool_calls')), 'done': response.get('done'),
            'done_reason': response.get('done_reason'), 'prompt_tokens': response.get('prompt_eval_count'),
            'completion_tokens': response.get('eval_count'), 'total_duration_ns': response.get('total_duration')}
        self.events.emit('native_response_metadata', **self.telemetry)
        (self.events.path.parent / 'response.txt').write_text(self.events.clean(content), encoding='utf-8')
        if message.get('tool_calls'):
            raise ValueError('Unexpected tool response')
        return LLMResponse(content=content, prompt_tokens=response.get('prompt_eval_count') or 0,
                           completion_tokens=response.get('eval_count') or 0)


def worker(path):
    job = json.loads(path.read_text(encoding='utf-8'))
    if type(job['thinking']) is not bool:
        raise TypeError('Thinking must be a boolean')
    events = Events(path.parent / 'trace.jsonl', path.parent.name)
    native = NativeLLM(job, events)
    config = RunConfig(model=job['model'], token_budget=15000, max_output_tokens=2048, context_tokens=16000)
    llm = BudgetLLM(native, config, events)
    result = {'patch_applied': False, 'status': 'provider_error'}
    data = {k: job[k] for k in ('description', 'allowed_files', 'files')}
    messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}]
    result['prompt_sha256'] = hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()
    try:
        response = llm.chat(messages, tools=[])
        if native.telemetry['done_reason'] == 'length':
            result['status'] = 'output_truncated'
        elif not response.content.strip():
            result['status'] = 'empty_final_answer'
        else:
            try:
                result['edited_files'] = apply_patch_json(response.content, Path(job['workspace']), job['allowed_files'], job['files'])
                result.update(patch_applied=True, status='patch_applied')
            except (ValueError, TypeError, KeyError, OSError) as exc:
                result.update(status='invalid_patch', error=f'{type(exc).__name__}: {exc}')
    except BudgetExceeded as exc:
        result.update(status='budget_exceeded', error=str(exc))
    except Exception as exc:  # noqa: BLE001 - retain failed calibration attempts
        result.update(status='provider_error', error=f'{type(exc).__name__}: {exc}')
    result.update(metrics=llm.metrics(), native=native.telemetry)
    (path.parent / 'worker-result.json').write_text(json.dumps(events.clean(result), indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    worker(parser.parse_args().worker)
