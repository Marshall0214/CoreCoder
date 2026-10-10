"""Replay one recorded first response, charge its usage, then allow live correction."""
import hashlib
import json
from pathlib import Path

from corecoder.llm import LLMResponse
from docs.experiments import deepseek_high_provider_v1 as original

PROVIDERS = original.PROVIDERS
identity = original.identity
CheckedBudgetLLM = original.CheckedBudgetLLM
SEED = Path(__file__).resolve().parents[2] / '.tmp/real-defects/caller-fallback-context-v1-20261009/click-flag-envvar/deepseek-high'


def seed_paths():
    return [SEED / name for name in ('initial-messages.json', 'initial-response.txt', 'worker-result.json')]


class Provider(original.Provider):
    def __init__(self, policy, events, client=None):
        super().__init__(policy, events, client)
        self.seed_hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in seed_paths()}

    def chat(self, messages, tools=None, max_tokens=8192):
        if self.calls:
            return super().chat(messages, tools, max_tokens)
        if tools:
            raise ValueError('Replay has no tools')
        if any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != h for p, h in self.seed_hashes.items()):
            raise ValueError('Replay source changed')
        recorded = json.loads((SEED / 'initial-messages.json').read_text(encoding='utf-8'))
        if messages != recorded:
            raise ValueError('Replay requires identical initial request')
        worker = json.loads((SEED / 'worker-result.json').read_text(encoding='utf-8'))
        call = worker['provider_calls'][0]
        if (worker['initial']['status'] != 'completed' or call['finish_reason'] != 'stop'
                or call['model_returned'] != self.model or call['effective_output_limit'] != max_tokens
                or len(worker['provider_calls']) != 1):
            raise ValueError('Require one valid recorded initial response with identical ceiling')
        content = (SEED / 'initial-response.txt').read_text(encoding='utf-8')
        root = self.events.path.parent / 'provider-call-01'
        root.mkdir(exist_ok=False)
        (root / 'response.txt').write_text(content, encoding='utf-8')
        (root / 'replay.json').write_text(json.dumps({'source_hashes': self.seed_hashes,
            'usage_policy': 'Charge historical initial usage; zero new API cost for replay'}, indent=2), encoding='utf-8')
        self.calls.append(dict(call, replayed=True))
        self.events.emit('initial_response_replayed', tokens_charged=call['total_tokens'])
        return LLMResponse(content=content, prompt_tokens=call['prompt_tokens'], completion_tokens=call['completion_tokens'])
