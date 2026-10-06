import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from corecoder.llm import LLMResponse
from docs.experiments.staged_compact_live_v1 import patch
from evals.process import run_process
from evals.runtime import BudgetLLM, Events
from evals.staged_repair import patch_staged
from tests.test_staged_repair import Provider
from tests.test_staged_replay import setup_checkpoint


def test_adapter_baseline_request_and_accounting_match_original_replay(tmp_path):
    source, config, checkpoint = setup_checkpoint(tmp_path)
    providers, results = [], []
    for arm in ('original', 'adapter'):
        workspace = tmp_path / arm
        shutil.copytree(source, workspace)
        provider = Provider([LLMResponse(content='{"edits": []}')])
        events = Events(tmp_path / f'{arm}.jsonl', arm)
        llm = BudgetLLM(provider, config, events)
        result = (patch_staged(llm, workspace, 'envvar', ['entry.py'], config, events,
                               lambda logs: {'passed': True}, checkpoint, replay=True) if arm == 'original'
                  else patch(llm, workspace, checkpoint, config, events, 'read-first'))
        assert llm.config is config
        providers.append(provider)
        results.append(result)
    assert providers[0].requests == providers[1].requests
    for key in ('patch_prompt_hash', 'patch_non_evidence_hash', 'candidate_pool_hash', 'evidence_hash', 'budget_accounting'):
        assert results[0][key] == results[1][key]


def test_compact_request_changes_only_fragments_and_keeps_single_call(tmp_path):
    source, config, checkpoint = setup_checkpoint(tmp_path)
    before = json.dumps(checkpoint, sort_keys=True)
    payloads = []
    for policy in ('read-first', 'compact-read-first-v1'):
        workspace = tmp_path / policy
        shutil.copytree(source, workspace)
        provider = Provider([LLMResponse(content='{"edits": []}')])
        llm = BudgetLLM(provider, config, Events(tmp_path / f'{policy}.jsonl', policy))
        result = patch(llm, workspace, checkpoint, config, llm.events, policy)
        assert result['status'] == 'completed' and llm.calls == 1
        assert provider.requests[0][1] == []
        assert result['budget_accounting']['actual_worker_tokens'] == 120
        assert not result['budget_accounting']['shared_localization_executed_here']
        payloads.append(json.loads(provider.requests[0][0][1]['content']))
    assert payloads[0].pop('fragments') != payloads[1].pop('fragments')
    assert payloads[0] == payloads[1]
    assert before == json.dumps(checkpoint, sort_keys=True)


def test_adapter_rejects_source_drift_and_nonfresh_counter_before_model(tmp_path):
    source, config, checkpoint = setup_checkpoint(tmp_path)
    provider = Provider([LLMResponse(content='must not be called')])
    llm = BudgetLLM(provider, config, Events(tmp_path / 'trace.jsonl', 'replay'))
    llm.spent = 1
    with pytest.raises(ValueError, match='fresh'):
        patch(llm, source, checkpoint, config, llm.events, 'compact-read-first-v1')
    llm.spent = 0
    (source / 'entry.py').write_bytes(b'changed')
    with pytest.raises(ValueError, match='version'):
        patch(llm, source, checkpoint, config, llm.events, 'compact-read-first-v1')
    assert provider.requests == []


def test_isolated_worker_starts_in_model_environment_and_rejects_bad_protocol(tmp_path):
    source, config, checkpoint = setup_checkpoint(tmp_path)
    root = Path(__file__).resolve().parents[1]
    job = tmp_path / 'job.json'
    job.write_text(json.dumps({'config': config.to_dict(), 'run_id': 'startup', 'protocol_sha256': 'changed',
                               'workspace': str(source), 'checkpoint': checkpoint}), encoding='utf-8')
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    result = run_process([sys.executable, str(root / 'docs/experiments/staged_compact_live_v1.py'),
                          '--worker', str(job)], source, 30, tmp_path / 'stdout.txt', tmp_path / 'stderr.txt', env)
    assert result['returncode'] == 0 and not result['timed_out']
    worker = json.loads((tmp_path / 'worker-result.json').read_text(encoding='utf-8'))
    assert worker['status'] == 'agent_error' and 'Protocol changed' in worker['error']
    assert worker['metrics'] is None  # Rejected before constructing or calling the model.
