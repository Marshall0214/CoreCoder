"""Unlimited local runs account real usage without silently substituting a large cap."""
import json
import time

import pytest

from evals import local50
from evals import local50_unmetered as unmetered
from evals.runtime import Events
from repairflow.issue_providers import OllamaProvider, ProviderFailure, UsageResponse


class LocalReplies(OllamaProvider):
    def __init__(self, reply):
        super().__init__('qwen3.5:27b', time.monotonic() + 60)
        self.reply = reply

    def chat(self, messages, tools=None):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_large_context_and_cumulative_usage_never_trigger_token_stop(tmp_path):
    events = Events(tmp_path / 'events.jsonl', 'unlimited')
    provider = LocalReplies(UsageResponse(content='{}', reported_usage={'prompt_tokens': 20000, 'completion_tokens': 3000}))
    llm = unmetered.ObservedLocalLLM(provider, unmetered.LocalConfig(), events)
    for _ in range(4):
        llm.chat([{'role': 'user', 'content': 'large input ' * 10000}], tools=[])
    assert llm.metrics()['prompt_tokens'] == 80000
    assert llm.metrics()['completion_tokens'] == 12000 and llm.calls == 4
    assert llm.metrics()['token_budget'] is None
    assert 'budget_blocked' not in (tmp_path / 'events.jsonl').read_text()


def test_failed_response_preserves_native_usage(tmp_path):
    failure = ProviderFailure('incomplete_model_response', reported_usage={'prompt_tokens': 100, 'completion_tokens': 30})
    llm = unmetered.ObservedLocalLLM(LocalReplies(failure), unmetered.LocalConfig(), Events(tmp_path / 'events', 'id'))
    with pytest.raises(ProviderFailure):
        llm.chat([{'role': 'user', 'content': 'test'}])
    assert llm.metrics()['failed_calls'] == 1 and llm.metrics()['prompt_tokens'] == 100


def test_missing_usage_is_not_reported_as_measured_zero(tmp_path):
    llm = unmetered.ObservedLocalLLM(LocalReplies(UsageResponse(content='{}')), unmetered.LocalConfig(),
                                     Events(tmp_path / 'events', 'id'))
    llm.chat([{'role': 'user', 'content': 'test'}])
    assert llm.metrics()['usage_status'] == 'unknown' and llm.metrics()['prompt_tokens'] is None


def test_unlimited_predictions_are_explicit_in_provider(monkeypatch):
    seen = {}

    def chat(self, messages, tools=None, max_tokens=2048):
        seen['max_tokens'] = max_tokens
        return UsageResponse(content='{}')

    monkeypatch.setattr(OllamaProvider, 'chat', chat)
    unmetered.UnlimitedLocalProvider('qwen3.5:27b', time.monotonic() + 10).chat([])
    assert seen == {'max_tokens': -1}


def test_non_local_provider_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='local Ollama'):
        unmetered.ObservedLocalLLM(object(), unmetered.LocalConfig(), Events(tmp_path / 'events', 'id'))


def test_batch_routes_workers_without_losing_subprocess_constants(tmp_path, monkeypatch):
    invocations = []
    original_module = local50.subprocess
    monkeypatch.setattr(unmetered.subprocess, 'run', lambda args, **kwargs: invocations.append((args, kwargs)))

    def execute(path, resume):
        assert path == tmp_path and resume is True
        assert local50.subprocess.STDOUT is original_module.STDOUT
        local50.subprocess.run(['python', '-B', '-m', 'evals.local50', '--worker', 'job.json'],
                               stderr=local50.subprocess.STDOUT, check=False)
        local50.subprocess.run(['python', '-B', '-m', 'deploy.langfuse.local50', '--batch', str(path)], check=False)
        return {'status': 'completed'}

    monkeypatch.setattr(local50, 'execute', execute)
    assert unmetered.execute(tmp_path)['status'] == 'completed'
    assert invocations[0][0][3] == 'evals.local50_unmetered'
    assert invocations[1][0][3] == 'deploy.langfuse.local50'
    assert local50.subprocess is original_module


def test_batch_restores_controller_binding_on_failure(tmp_path, monkeypatch):
    original_module = local50.subprocess

    def fail(*args, **kwargs):
        raise RuntimeError('controller interrupted')

    monkeypatch.setattr(local50, 'execute', fail)
    with pytest.raises(RuntimeError):
        unmetered.execute(tmp_path)
    assert local50.subprocess is original_module


def test_worker_uses_checkpoint_and_keeps_grading_private(tmp_path, monkeypatch):
    source = tmp_path / 'before'
    source.mkdir()
    (source / 'code.py').write_text('def f():\n    return 1\n', encoding='utf-8')
    private = tmp_path / 'private-grading'
    private.mkdir()
    (private / 'test_hidden.py').write_text('PRIVATE-GRADING-MARKER', encoding='utf-8')
    folder = tmp_path / 'task'
    task = {'instance_id': 'simple', 'repo': 'example/pkg', 'base_commit': 'source-hash',
            'problem_statement': 'f must return 2'}
    unmetered.write(folder / 'public.json', task)
    unmetered.write(folder / 'job.json', {'source': str(source), 'source_hash': local50.digest(local50.snapshot(source)),
                                        'public_sha256': unmetered.sha(folder / 'public.json')})
    replies = iter([{'action': 'read_symbol', 'arguments': {'path': 'code.py', 'symbol': 'f'}},
                    {'edits': [{'file': 'code.py', 'old': 'return 1', 'new': 'return 2'}]}])

    class Provider(unmetered.UnlimitedLocalProvider):
        def chat(self, messages, **kwargs):
            assert str(private) not in json.dumps(messages) and 'PRIVATE-GRADING-MARKER' not in json.dumps(messages)
            return UsageResponse(content=json.dumps(next(replies)),
                                 reported_usage={'prompt_tokens': 20000, 'completion_tokens': 3000})

    original = local50.BudgetLLM
    monkeypatch.setenv('CORECODER_LANGFUSE_ENABLED', '0')
    monkeypatch.setattr(unmetered, 'UnlimitedLocalProvider', Provider)
    unmetered.worker(folder / 'job.json')
    result = local50.read(folder / 'agent/report.json')
    assert result['status'] == 'candidate_generated' and result['changed_files'] == ['code.py']
    assert result['metrics']['prompt_tokens'] == 40000 and result['limits']['token_budget'] is None
    assert result['protocol'] == unmetered.PROTOCOL and local50.BudgetLLM is original
