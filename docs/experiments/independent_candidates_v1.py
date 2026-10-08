"""Independent source candidates with public-only selection and a shared task budget."""
import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path

from corecoder.llm import LLMResponse, ToolCall
from docs.experiments import frozen_feedback_v1 as guarded
from docs.experiments import provider_compare_worker_v1 as adapters
from evals.runner import digest, snapshot
from evals.runtime import Events

previous = guarded.previous
SECOND_TEMPERATURE = 0.7


class SamplingProvider(adapters.Provider):
    """Both comparison arms use the same first/second-call sampling schedule."""
    def chat(self, messages, tools=None):
        if tools:
            raise ValueError('Tools are outside this structured patch protocol')
        request = {'model': self.model, 'messages': messages, 'stream': False, 'temperature': 0 if not self.calls else SECOND_TEMPERATURE, 'top_p': 1, 'max_tokens': 2048}
        request.update({key: value for key, value in self.settings.items() if key in {'reasoning_effort', 'extra_body'}})
        number = len(self.calls) + 1
        root = self.events.path.parent / f'provider-call-{number:02d}'
        root.mkdir(exist_ok=False)
        (root / 'request.json').write_text(json.dumps(self.events.clean(request), indent=2), encoding='utf-8')
        started = time.perf_counter()
        call = {'temperature': request['temperature'], 'provider': self.name, 'model_requested': self.model, 'request_sha256': hashlib.sha256(
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



def run_candidate(llm, job, events):
    root, workspace = events.path.parent, Path(job['workspace'])
    guarded.validate(job, root)
    original = root / 'original-workspace'
    shutil.copytree(workspace, original)
    result = {'status': 'agent_error', 'published': False, 'selected_candidate': None,
              'protocol': 'independent-candidates-v1', 'candidates': []}
    seen = {}
    try:
        for number, stage in enumerate(('initial', 'alternative'), 1):
            if number == 2:
                guarded.restore(workspace, original, root)
                guarded.validate(job, root)
            # No prior candidate or failure observations enter this request.
            candidate = previous.request(llm, workspace, job, job['evidence'], root, stage)
            candidate['number'] = number
            result['candidates'].append(candidate)
            if candidate['status'] == 'completed':
                source_hash = digest(snapshot(workspace))
                candidate['source_hash'] = source_hash
                if source_hash in seen:
                    candidate['duplicate_of'] = seen[source_hash]
                    events.emit('duplicate_candidate_rejected', number=number, duplicate_of=seen[source_hash])
                    continue
                seen[source_hash] = number
                checks = guarded.checked(workspace, job, root, stage)
                candidate['checks'] = checks
                for name in ('harness', 'frozen_harness'):
                    if digest(snapshot(Path(job[name]))) != job[name + '_hash']:
                        raise ValueError('Certified public harness changed')
                if guarded.valid(checks):
                    result.update(status='completed', published=True, selected_candidate=number)
                    break
                if not guarded.executable(checks):
                    result['stop_reason'] = 'public_execution_failure'
                    break
            if candidate['status'] == 'budget_exceeded':
                result['stop_reason'] = 'budget_exceeded'
                break
        if not result['published']:
            result['status'] = 'no_valid_candidate'
    except Exception as exc:  # noqa: BLE001 - failed selection must roll back
        result.update(status='agent_error', error_type=type(exc).__name__, published=False)
    finally:
        if not result['published']:
            guarded.restore(workspace, original, root)
            events.emit('independent_candidates_rolled_back', starting_version_restored=True)
        else:
            events.emit('independent_candidate_retained', selected=result['selected_candidate'])
        result['metrics'] = llm.metrics()
        result['final_source_hash'] = digest(snapshot(workspace))
        result['original_restored'] = result['final_source_hash'] == job['original_hash']
    return result


def worker(path):
    job = json.loads(path.read_text(encoding='utf-8'))
    events = Events(path.parent / 'trace.jsonl', job['policy'])
    provider = llm = None
    result = {'status': 'agent_error', 'published': False}
    started = time.monotonic()
    try:
        config = previous.repair.config()
        previous.repair.check_identity(config)
        provider = SamplingProvider('qwen', events)
        llm = adapters.CheckedBudgetLLM(provider, config, events)
        workflow = guarded.run_candidate if job['policy'] == 'feedback' else run_candidate
        if job['policy'] not in ('feedback', 'independent'):
            raise ValueError('Unknown comparison policy')
        result = workflow(llm, job, events)
        previous.repair.check_identity(config)
    except Exception as exc:  # noqa: BLE001 - preserve every failed attempt
        result.update(status='agent_error', error_type=type(exc).__name__, published=False)
        if (path.parent / 'original-workspace').exists():
            guarded.restore(Path(job['workspace']), path.parent / 'original-workspace', path.parent)
    finally:
        result.update(metrics=llm.metrics() if llm else None, provider_calls=provider.calls if provider else [],
                      seconds=round(time.monotonic() - started, 4))
        previous.write_json(path.parent / 'worker-result.json', events.clean(result))
        if provider:
            provider.client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    worker(parser.parse_args().worker.resolve())
