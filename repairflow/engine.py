"""One shared execution path for CLI and approval service; frozen strategies reused."""
import hashlib
import importlib.metadata
import json
import shutil
import sys
from dataclasses import dataclass, replace
from pathlib import Path

from corecoder.llm import LLMResponse
from docs.experiments import deepseek_high_provider_v1 as provider
from docs.experiments.coverage_context_v2 import retrieve
from docs.experiments.provider_compare_worker_v1 import deepseek_key
from evals.runner import changes, digest, snapshot
from evals.runtime import BudgetLLM, Events
from evals.schema import RunConfig
from repairflow import checks, strategy
from repairflow.bundles import ROOT, load, read, write


@dataclass(frozen=True)
class DeliveryConfig(RunConfig):
    def __post_init__(self):
        if self.mode == 'replay':
            replace(self, mode='live')  # Validate all original constraints without expanding eval modes.
        else:
            super().__post_init__()


def config(mode='live'):
    if mode not in {'live', 'replay'}:
        raise ValueError('Require live or replay mode')
    return DeliveryConfig(mode=mode, model='deepseek-flash', base_url='https://api.deepseek.com',
                     reasoning_effort='high', max_rounds=2, max_output_tokens=32768,
                     token_budget=60000, context_tokens=65536, wall_timeout=1200, output_policy='remaining')


class ReplayProvider:
    """Only reproduce an exact historical single-call prompt; never contact a model."""
    def __init__(self, bundle):
        self.record = read(Path(bundle) / 'replay.json')
        self.calls = []
        self.model = 'deepseek-flash'

    def chat(self, messages, tools=None, max_tokens=32768):
        record = self.record
        prompt_hash = hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()
        call = record['call']
        if (self.calls or tools or prompt_hash != record['prompt_hash'] or call['finish_reason'] != 'stop'
                or call['model_returned'] != 'deepseek-flash' or call['completion_tokens'] > max_tokens):
            raise ValueError('Replay prompt, response identity or budget mismatch')
        self.calls.append(dict(call, replay=True))
        return LLMResponse(content=record['content'], prompt_tokens=call['prompt_tokens'],
                           completion_tokens=call['completion_tokens'])

    def close(self):
        pass


def implementation():
    paths = {Path(__file__).resolve()}
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if name:
            p = Path(name).resolve()
            if p.suffix == '.py' and p.is_relative_to(ROOT) and p.parts[-2] != 'tests':
                paths.add(p)
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def environment():
    versions = {}
    for name in ('openai', 'fastapi', 'langgraph', 'langgraph-checkpoint-sqlite', 'pydantic'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {'python': sys.version, 'executable': sys.executable, 'dependencies': versions}


def execute(bundle, mode, output, provider_factory=None):
    """Copy trusted source, repair with public evidence, grade only after generation."""
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    data, settings = load(bundle), config(mode)
    if output.exists() or output.is_relative_to(bundle) or bundle.is_relative_to(output):
        raise ValueError('Require fresh nonoverlapping output')
    if mode == 'replay' and 'replay_sha256' not in data:
        raise ValueError('Bundle has no exact replay record')
    output.mkdir(parents=True)
    events = Events(output / 'trace.jsonl', output.name)
    versions = implementation()
    write(output / 'provenance.json', {'strategy': data['strategy'], 'bundle_hash': data['bundle_hash'],
                                      'config': settings.to_dict(), 'implementation': versions,
                                      'environment': environment(),
                                      'execution_mode': mode, 'fresh_inference': mode == 'live'})
    workspace = output / 'workspace'
    shutil.copytree(bundle / 'source', workspace)
    events.emit('stage', stage='localizing')
    context = retrieve(workspace, data['allowed_files'], data['description'],
                       (bundle / 'public/test_admission.py').read_text(encoding='utf-8'))
    write(output / 'context-selection.json', context)
    job = {k: data[k] for k in ('task_id', 'package', 'source_root', 'description', 'description_hash', 'allowed_files')}
    job.update(workspace=str(workspace), original_hash=data['hashes']['source'], evidence=context['evidence'])
    for key, name in (('harness', 'public'), ('frozen_harness', 'frozen'), ('contract_harness', 'contract')):
        if name in data['hashes']:
            job[key], job[key + '_hash'] = str(bundle / name), data['hashes'][name]
    # Grader path and reference fixes are deliberately absent from the worker job.
    write(output / 'job.json', job)
    inner = None
    try:
        if provider_factory:
            inner = provider_factory(events)
        elif mode == 'replay':
            inner = ReplayProvider(bundle)
        else:
            from openai import OpenAI

            inner = provider.Provider('deepseek-high', events, client=OpenAI(
                api_key=deepseek_key(), base_url=settings.base_url, timeout=480, max_retries=0))
        llm = BudgetLLM(inner, settings, events) if mode == 'replay' else provider.CheckedBudgetLLM(inner, settings, events)
        events.emit('stage', stage='repairing')
        result = strategy.run_candidate(llm, job, events)
        result['provider_calls'] = inner.calls
        write(output / 'worker-result.json', events.clean(result))
    finally:
        if inner:
            inner.close()
    events.emit('stage', stage='independent_verification')
    grade = output / 'verification'
    grade.mkdir()
    case = dict(data, before=str(bundle / 'source'), checks=str(bundle / 'grader'))
    verified = checks.verify(case, workspace, grade)
    # Keep the same final checks and acceptance predicate as the full-pool runner.
    public = strategy.previous.public_check(workspace, job['harness'], data['package'], data['source_root'], output / 'final-public')
    frozen = strategy.previous.public_check(workspace, job['frozen_harness'], data['package'], data['source_root'], output / 'final-frozen')
    if load(bundle)['bundle_hash'] != data['bundle_hash']:
        raise ValueError('Bundle changed during execution')
    if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha for name, sha in versions.items()):
        raise ValueError('Implementation changed during execution')
    accepted = (result['status'] == 'completed' and verified['passed'] and strategy.previous.all_pass(public)
                and strategy.previous.all_pass(frozen) and strategy.valid(result.get('final_checks', {})))
    if not accepted and digest(snapshot(workspace)) != data['hashes']['source']:
        strategy.restore(workspace, bundle / 'source', output)
        events.emit('independent_rejection_rolled_back')
    _, patch = changes(snapshot(bundle / 'source'), snapshot(workspace))
    (output / 'patch.diff').write_text(patch, encoding='utf-8')
    report = {'status': 'passed' if accepted else result['status'] if result['status'] != 'completed' else 'failed_verification',
              'accepted': bool(accepted), 'execution_mode': mode, 'fresh_inference': mode == 'live',
              'verification': verified, 'public': public, 'frozen': frozen,
              'metrics': result['metrics'], 'historical_usage_only': mode == 'replay',
              'fresh_model_calls': len(inner.calls) if mode == 'live' else 0,
              'original_unchanged': digest(snapshot(workspace)) == data['hashes']['source'],
              'artifacts': str(output), 'bundle_hash': data['bundle_hash'],
              'limits': 'Trusted known-task bundle; hand-authored independent tests, not full upstream suite. '
                        'Execution approval precedes inference; source checkout is never modified.'}
    write(output / 'report.json', events.clean(report))
    events.emit('stage', stage='succeeded' if accepted else 'failed', accepted=bool(accepted))
    return report
