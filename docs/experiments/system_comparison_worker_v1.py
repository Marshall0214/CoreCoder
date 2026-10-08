"""Original seven-tool CoreCoder vs optional structured repair, common provider budgets."""
import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

from corecoder.llm import LLMResponse, ToolCall
from docs.experiments import frozen_feedback_v1 as guarded
from evals.runner import digest, snapshot
from evals.runtime import BudgetLLM, Events, ScopedTool

previous = guarded.previous


class ToolProvider(previous.Provider):
    def chat(self, messages, tools=None, **kwargs):
        number = len(self.calls) + 1
        root = self.events.path.parent / f'provider-call-{number:02d}'
        root.mkdir()
        request = {'model': self.model, 'messages': messages, 'stream': False, 'temperature': 0, 'top_p': 1,
                   'max_tokens': 2048, 'reasoning_effort': 'none'}
        if tools:
            request['tools'] = tools
        previous.write_json(root / 'request.json', self.events.clean(request))
        call = {'response_received': False, 'model_requested': self.model}
        self.calls.append(call)
        started = time.monotonic()
        try:
            response = self.client.chat.completions.create(**request)
        finally:
            call['seconds'] = round(time.monotonic() - started, 4)
        choice, usage = response.choices[0], response.usage
        message = choice.message
        call.update(response_received=True, model_returned=response.model, finish_reason=choice.finish_reason,
                    prompt_tokens=getattr(usage, 'prompt_tokens', None), completion_tokens=getattr(usage, 'completion_tokens', None),
                    total_tokens=getattr(usage, 'total_tokens', None),
                    reasoning_present=bool(getattr(message, 'reasoning_content', None) or getattr(message, 'reasoning', None)),
                    reasoning_tokens=getattr(getattr(usage, 'completion_tokens_details', None), 'reasoning_tokens', None))
        content = message.content or ''
        (root / 'response.txt').write_text(self.events.clean(content), encoding='utf-8')
        calls = []
        for tool in message.tool_calls or []:
            try:
                args = json.loads(tool.function.arguments)
            except (ValueError, TypeError):
                args = {'invalid_arguments': tool.function.arguments}
            calls.append(ToolCall(tool.id, tool.function.name, args))
        self.events.emit('provider_response', **call)
        return LLMResponse(content=content, tool_calls=calls, prompt_tokens=call['prompt_tokens'] or 0,
                           completion_tokens=call['completion_tokens'] or 0)


class ToolBudget(BudgetLLM):
    def chat(self, messages, tools=None, **kwargs):
        response = super().chat(messages, tools=tools, **kwargs)
        call = self.inner.calls[-1]
        if call['model_returned'] != self.model:
            raise previous.baseline.InvalidCompletion('model_identity_mismatch')
        if call['reasoning_present'] or call['reasoning_tokens']:
            raise previous.baseline.InvalidCompletion('unexpected_thinking')
        if call['finish_reason'] not in {'stop', 'tool_calls'}:
            raise previous.baseline.InvalidCompletion('output_truncated')
        if not response.content.strip() and not response.tool_calls:
            raise previous.baseline.InvalidCompletion('empty_final_answer')
        return response


def upstream(path):
    spec = importlib.util.spec_from_file_location('benchmark_upstream_corecoder', path / '__init__.py',
                                                 submodule_search_locations=[str(path)])
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # The historical __init__ uses absolute imports; select its frozen agent
    # explicitly rather than accidentally using the current package export.
    from importlib import import_module
    module.Agent = import_module(spec.name + '.agent').Agent
    return module


def original(llm, job, events):
    root, workspace = events.path.parent, Path(job['workspace'])
    guarded.validate(job, root)
    engine = Path(job['upstream'])
    if digest(snapshot(engine)) != job['upstream_hash']:
        raise ValueError('Original engine changed')
    module = upstream(engine)
    from importlib import import_module
    registry = import_module(module.__name__ + '.tools')
    permission = import_module(module.__name__ + '.permissions').Permission(allow_all=True)
    classes = (registry.ReadFileTool, registry.GlobTool, registry.GrepTool, registry.EditFileTool,
               registry.WriteFileTool, registry.TodoWriteTool, registry.BashTool)
    tools = [ScopedTool(cls(), workspace, job['allowed_files'], events, 15) for cls in classes]
    command = 'python -m unittest discover -s .eval-logs/public-tests -v'
    bash = tools[-1]
    bash.visible_command = command

    def visible(logs):
        outcomes = {label: previous.public_check(workspace, job[name], job['package'], job['source_root'], logs / label)
                    for label, name in [('public', 'harness'), ('frozen', 'frozen_harness')]}
        output = ''.join(label + ':\n' + (logs / label / (group + '.stderr.txt')).read_text(encoding='utf-8', errors='replace')
                         for label in outcomes for group in ('Reproduce', 'Preserve'))
        (logs / 'stdout.txt').write_text(output, encoding='utf-8')
        (logs / 'stderr.txt').write_text('', encoding='utf-8')
        return {'returncode': 0 if all(previous.all_pass(v) for v in outcomes.values()) else 1,
                'timed_out': any(g['timed_out'] for v in outcomes.values() for g in v.values()),
                'stdout': 'stdout.txt', 'stderr': 'stderr.txt'}

    # Each visible invocation has fresh logs, including parallel test calls.
    import uuid
    def visible_unique(logs):
        unique = logs / uuid.uuid4().hex
        unique.mkdir()
        info = visible(unique)
        return dict(info, stdout=str(Path(unique.name) / info['stdout']), stderr=str(Path(unique.name) / info['stderr']))

    bash.visible_runner = visible_unique

    agent = module.Agent(llm=llm, tools=tools, permission=permission, max_rounds=12, max_context_tokens=16000)
    agent._todo = tools[-2].inner
    prompt = (job['description'] + '\nRepair source in this workspace. Allowed source files: ' +
              json.dumps(job['allowed_files']) + '\nPublic tests: ' + command +
              '\nThe declared command runs both public-tests and frozen-tests under .eval-logs.' +
              '\nDo not edit tests. Complete the repair within the declared budget.')
    reply = agent.chat(prompt)
    return {'status': 'round_limit' if reply == '(reached maximum tool-call rounds)' else 'completed',
            'final_message': events.clean(reply), 'published': False}


def worker(path):
    job = json.loads(path.read_text(encoding='utf-8'))
    root, workspace = path.parent, Path(job['workspace'])
    events = Events(root / 'trace.jsonl', job['policy'])
    provider = llm = None
    result = {'status': 'agent_error', 'published': False}
    started = time.monotonic()
    # Native tools need task-local relative paths. Structured workers use
    # absolute paths and must stay outside directories they may roll back.
    if job['policy'] == 'original':
        os.chdir(workspace)
    try:
        previous.repair.check_identity(previous.repair.config())
        if job['policy'] == 'original':
            provider = ToolProvider('qwen', events)
            llm = ToolBudget(provider, previous.repair.config(), events)
            result = original(llm, job, events)
        else:
            provider = previous.Provider('qwen', events)
            llm = previous.CheckedBudgetLLM(provider, previous.repair.config(), events)
            if job['policy'] == 'full':
                result = guarded.run_candidate(llm, job, events)
            elif job['policy'] == 'retrieval':
                guarded.validate(job, root)
                result = previous.request(llm, workspace, job, job['evidence'], root, 'initial')
                result['published'] = False
            else:
                raise ValueError('Unknown policy')
        previous.repair.check_identity(previous.repair.config())
    except Exception as exc:  # noqa: BLE001 - all failures retained and scored
        status = str(exc) if isinstance(exc, previous.baseline.InvalidCompletion) else 'budget_exceeded' if isinstance(exc, previous.baseline.BudgetExceeded) else 'agent_error'
        result.update(status=status, published=False, error_type=type(exc).__name__, error=events.clean(str(exc)))
        if job['policy'] == 'full' and (root / 'original-workspace').exists():
            guarded.restore(workspace, root / 'original-workspace', root)
    finally:
        result.update(metrics=llm.metrics() if llm else None, provider_calls=provider.calls if provider else [],
                      seconds=round(time.monotonic() - started, 4), source_hash=digest(snapshot(workspace)))
        previous.write_json(root / 'worker-result.json', events.clean(result))
        if provider:
            provider.client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    worker(parser.parse_args().worker.resolve())
