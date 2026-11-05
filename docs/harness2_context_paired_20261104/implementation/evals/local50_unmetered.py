"""Own checkpoint Agent, local inference with token accounting but no token cutoffs."""
import argparse
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace

from evals import local50, repository_checkpoint
from evals.context_policy import request_breakdown
from evals.runtime import BudgetLLM
from evals.swebench_mini import ROOT, sha, write
from repairflow.issue_providers import OllamaProvider

PROTOCOL = 'local50-unmetered-checkpoint-v1'
_INITIALIZE = local50.initialize


@dataclass(frozen=True)
class LocalConfig:
    mode: str = 'live'
    model: str = 'qwen3.5:27b'
    base_url: str = 'http://127.0.0.1:11434'
    max_rounds: int = 20
    token_budget: None = None
    max_output_tokens: None = None
    context_tokens: int = 65536  # Provider capacity, not an application preflight cutoff.
    wall_timeout: int = 1200
    output_policy: str = 'account_only'

    def to_dict(self):
        return asdict(self)


class UnlimitedLocalProvider(OllamaProvider):
    def chat(self, messages, tools=None, **kwargs):
        # Ollama's documented -1 means no configured prediction-token limit.
        return super().chat(messages, tools=tools, max_tokens=-1)


class ObservedLocalLLM(BudgetLLM):
    """Keep native successful/failed usage accounting; never block on token estimates."""
    def __init__(self, inner, config, events):
        if not isinstance(inner, OllamaProvider) or config != LocalConfig():
            raise ValueError('Token-unlimited mode is restricted to the fixed local Ollama configuration')
        super().__init__(inner, config, events)

    def chat(self, messages, tools=None, **kwargs):
        if kwargs:
            raise ValueError('Output-token overrides are disabled in this local-only run')
        breakdown = request_breakdown(messages, tools)
        self.events.emit('request_preflight', next_call=self.calls + 1, **breakdown,
                         token_budget=None, cumulative_enforced=False, context_preflight_enforced=False,
                         effective_max_output_tokens=None, provider_context_tokens=65536)
        self.calls += 1
        call_id, started = f'llm-{self.calls}', time.perf_counter()
        self.events.emit('llm_started', call_id=call_id, request_estimate=breakdown['request_estimate'],
                         message_count=len(messages))
        try:
            response = self.inner.chat(messages, tools=tools)
        except Exception as exc:
            usage = self._account_usage(exc, breakdown['request_estimate'], failed=True)
            self.events.emit('llm_failed', call_id=call_id, error=f'{type(exc).__name__}: {exc}', **usage)
            raise
        usage = self._account_usage(response, breakdown['request_estimate'])
        self.events.emit('llm_finished', call_id=call_id, seconds=round(time.perf_counter() - started, 4),
                         tools=[call.name for call in response.tool_calls], **usage)
        return response

    def metrics(self):
        return {**super().metrics(), 'budget_enforcement': 'none; local tokens accounted only',
                'token_budget': None, 'max_output_tokens': None, 'context_preflight_enforced': False,
                'provider_context_tokens': 65536}


def worker(path):
    # Change bindings only inside this worker process. Original files and old reports stay frozen.
    replacements = {'RunConfig': lambda **kwargs: LocalConfig(), 'BudgetLLM': ObservedLocalLLM,
                    'OllamaProvider': UnlimitedLocalProvider, 'RepositoryTools': repository_checkpoint.LedgerTools,
                    'explore': repository_checkpoint.explore}
    original = {key: getattr(local50, key) for key in replacements}
    try:
        for key, value in replacements.items():
            setattr(local50, key, value)
        local50.worker(path)
    finally:
        for key, value in original.items():
            setattr(local50, key, value)
    report_path = path.parent / 'agent/report.json'
    report = local50.read(report_path)
    report.update(protocol=PROTOCOL, policy='repository-checkpoint-v1',
                  token_limits_disabled=True, independent_grading='after_agent_termination',
                  not_comparable_to_historical_94_percent=True)
    write(report_path, report)


def initialize(output):
    protocol = _INITIALIZE(output)
    protocol.update(name=PROTOCOL, token_budget=None, max_output_tokens=None, context_tokens=65536,
                    context_preflight_enforced=False, ollama_num_predict=-1, policy='repository-checkpoint-v1',
                    comparison_scope='Own checkpoint loop without token cutoffs; not a budget-only v1 ablation',
                    extra_limits={'model_call_seconds': 480, 'provider_response_bytes': 4000000,
                                  'repeated_action_count': 3, 'consecutive_errors': 3,
                                  'candidate_dependency_reads': 2, 'stop_after_first_valid_candidate': True})
    for name in ('evals/local50_unmetered.py', 'evals/repository_checkpoint.py', 'evals/context_policy.py'):
        protocol['source_files'][name] = sha(ROOT / name)
    write(output / 'protocol.json', protocol)
    report = local50.read(output / 'report.json')
    report['protocol_sha256'] = sha(output / 'protocol.json')
    write(output / 'report.json', report)
    return protocol


def execute(output):
    original = local50.subprocess

    def launch(args, **kwargs):
        args = list(args)
        if len(args) > 4 and args[2:4] == ['-m', 'evals.local50'] and args[4] == '--worker':
            args[3] = 'evals.local50_unmetered'
        return subprocess.run(args, check=kwargs.pop('check', False), **kwargs)

    try:
        # Preserve original batch preparation, per-task grading, resume behavior and Langfuse publishing.
        delegated = SimpleNamespace(**vars(original))
        delegated.run = launch
        local50.subprocess = delegated
        return local50.execute(output, resume=True)
    finally:
        local50.subprocess = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path)
    group.add_argument('--worker', type=Path)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    path = (args.worker or args.output).resolve()
    if not path.is_relative_to(ROOT / '.tmp') or (os.name == 'nt' and path.drive.lower() != 'd:'):
        parser.error('Use project .tmp on D:')
    if args.worker:
        worker(path)
        return
    if not args.resume:
        initialize(path)
    protocol = local50.read(path / 'protocol.json')
    if protocol['name'] != PROTOCOL:
        parser.error('Resume only this exact local protocol')
    with (path / 'batch.lock').open('a+b') as lock:
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(execute(path)['summary']))


if __name__ == '__main__':
    main()
