import json
from dataclasses import replace

import pytest

from corecoder.llm import LLMResponse, ToolCall
from evals.runtime import BudgetLLM, Events
from evals.schema import RunConfig
from evals.staged_repair import localize_staged, object_hash, patch_staged
from tests.test_staged_repair import Provider


def setup_checkpoint(tmp_path):
    workspace = tmp_path / 'localization'
    workspace.mkdir()
    (workspace / 'entry.py').write_bytes(b'def envvar(value):\r\n    return value\r\n')
    config = RunConfig(mode='live', token_budget=10000)
    events = Events(workspace / 'trace.jsonl', 'localization')
    provider = Provider([LLMResponse(tool_calls=[ToolCall('read', 'read_file', {'file_path': 'entry.py'})]),
                         LLMResponse(content='located')])
    llm = BudgetLLM(provider, config, events)
    checkpoint = localize_staged(llm, workspace, 'envvar', ['entry.py'], config, events)
    assert llm.config is config
    assert checkpoint['metrics']['budget_accounted_tokens'] == 240
    return workspace, config, checkpoint


def branch(tmp_path, source, config, checkpoint, policy='read-first', mutate=None, description='envvar'):
    tmp_path.mkdir()
    (tmp_path / 'entry.py').write_bytes((source / 'entry.py').read_bytes())
    if mutate:
        mutate(tmp_path, checkpoint)
    patch = json.dumps({'edits': [{'file': 'entry.py', 'old': 'return value', 'new': 'return bool(value)'}]})
    provider = Provider([LLMResponse(content=patch)])
    llm = BudgetLLM(provider, config, Events(tmp_path / 'trace.jsonl', policy))
    result = patch_staged(llm, tmp_path, description, ['entry.py'], config, llm.events,
                          lambda logs: {'passed': True}, checkpoint, policy, replay=True)
    assert llm.config is config
    return result, llm, provider


def test_shared_checkpoint_is_reused_without_model_localization_or_double_billing(tmp_path):
    source, config, checkpoint = setup_checkpoint(tmp_path)
    original = json.dumps(checkpoint, sort_keys=True)
    a, left, p = branch(tmp_path / 'read', source, config, checkpoint)
    b, right, q = branch(tmp_path / 'seed', source, config, checkpoint, 'seed-first')
    assert json.dumps(checkpoint, sort_keys=True) == original
    assert a['candidate_pool_hash'] == b['candidate_pool_hash']
    assert a['localization_checkpoint_hash'] == b['localization_checkpoint_hash']
    assert a['patch_non_evidence_hash'] == b['patch_non_evidence_hash']
    assert a['evidence_hash'] != b['evidence_hash']
    for result, counter, provider in ((a, left, p), (b, right, q)):
        assert result['status'] == 'completed'
        assert counter.metrics()['llm_calls'] == 1 and len(provider.requests) == 1
        assert provider.requests[0][1] == []
        assert result['budget_accounting'] == {
            'actual_worker_tokens': 120, 'patch_tokens': 120, 'shared_localization_tokens': 240,
            'pipeline_equivalent_tokens': 360, 'shared_localization_executed_here': False}
    assert checkpoint['metrics']['budget_accounted_tokens'] + left.spent + right.spent == 480
    assert (source / 'entry.py').read_bytes().endswith(b'return value\r\n')
    assert (tmp_path / 'read/entry.py').read_bytes().endswith(b'return bool(value)\r\n')


@pytest.mark.parametrize('change', ['source', 'description', 'config', 'checksum', 'forged-content', 'cost'])
def test_replay_rejects_drift_before_any_model_call(tmp_path, change):
    source, config, checkpoint = setup_checkpoint(tmp_path)
    provider = Provider([LLMResponse(content='must not be called')])
    if change == 'source':
        (source / 'entry.py').write_bytes(b'changed')
    if change == 'config':
        config = replace(config, token_budget=20000)
    if change == 'checksum':
        checkpoint['description'] = 'tampered'
    if change == 'forged-content':
        checkpoint['pool']['seeds'][0]['content'] = 'invented source'
        checkpoint['localization_result']['candidate_pool_hash'] = object_hash(checkpoint['pool'])
    if change == 'cost':
        checkpoint['metrics']['budget_accounted_tokens'] += 1
    if change in {'forged-content', 'cost'}:
        checkpoint['checkpoint_hash'] = object_hash({k: v for k, v in checkpoint.items() if k != 'checkpoint_hash'})
    llm = BudgetLLM(provider, config, Events(tmp_path / 'replay.jsonl', 'replay'))
    with pytest.raises(ValueError):
        patch_staged(llm, source, 'different' if change == 'description' else 'envvar', ['entry.py'], config,
                      llm.events, lambda logs: {'passed': True}, checkpoint, replay=True)
    assert not provider.requests and llm.spent == 0
