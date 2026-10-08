import json

import pytest

from docs.experiments import failure_context_compare_v1 as comparison
from docs.experiments import failure_guided_context_v1 as guided
from evals.runner import digest, snapshot
from evals.runtime import Events


@pytest.fixture
def case(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    code = ('def entry():\n    return branch()\n\ndef branch():\n    secret = "do-not-log-local-values"\n    return 0\n\n'
            'def control():\n    return 1\n\ndef unused():\n    return 2\n')
    (workspace / 'example.py').write_text(code, encoding='utf-8')
    harness = tmp_path / 'public'
    harness.mkdir()
    (harness / 'test_admission.py').write_text(
        'import unittest\nimport example\n'
        'class Reproduce(unittest.TestCase):\n    def test_bug(self):\n        self.assertEqual(example.entry(), 1)\n'
        'class Preserve(unittest.TestCase):\n    def test_normal(self):\n        self.assertEqual(example.control(), 1)\n'
        'class Target(unittest.TestCase):\n    def test_private(self):\n        raise RuntimeError("must not execute")\n',
        encoding='utf-8')
    job = {'workspace': str(workspace), 'source_root': '.', 'package': 'example',
           'allowed_files': ['example.py'], 'harness': str(harness), 'harness_hash': digest(snapshot(harness))}
    index = guided.previous.baseline.functions.FunctionIndex(workspace, job['allowed_files'])
    index.refresh()
    names = {index.names[(c.path, c.start_line, c.end_line)]: c for c in index.chunks}
    seeds = guided.previous.baseline.functions.pack(index, [(1, names[n]) for n in ('entry', 'control', 'unused')])['evidence']
    return workspace, job, seeds


def test_public_trace_drives_new_function_selection(case, tmp_path):
    workspace, job, seeds = case
    before = digest(snapshot(workspace))
    observations = guided.probe(workspace, job, tmp_path / 'probe')
    assert all(g['usable'] for g in observations)
    assert observations[0]['data']['records'][0]['passed'] is False
    assert observations[1]['data']['records'][0]['passed'] is True
    text = json.dumps(observations)
    assert 'do-not-log-local-values' not in text
    assert 'must not execute' not in text
    packed = guided.select(workspace, job['allowed_files'], seeds, observations)
    symbols = {r['symbol']: r for r in packed['evidence']}
    assert symbols['branch']['reason'] == 'failed_public_execution'
    assert symbols['entry']['reason'] == symbols['control']['reason'] == 'retained_anchor'
    assert len(packed['evidence']) <= 5 and sum(len(r['content']) for r in packed['evidence']) <= 6000
    assert digest(snapshot(workspace)) == before


@pytest.mark.parametrize('observation', [[], [{'usable': False, 'data': {}}]])
def test_unusable_probe_falls_back_without_dropping_seeds(case, observation):
    workspace, job, seeds = case
    packed = guided.select(workspace, job['allowed_files'], seeds, observation)
    assert packed['metadata']['policy'] == 'failure-context-fallback'
    assert [r['symbol'] for r in packed['evidence']] == [r['symbol'] for r in seeds]


def test_reindexed_fragments_use_current_hash(case, tmp_path):
    import shutil
    workspace, job, seeds = case
    before = tmp_path / 'original'
    shutil.copytree(workspace, before)
    p = workspace / 'example.py'
    p.write_text(p.read_text().replace('return 0', 'return -1').replace('return 2', 'return 3'), encoding='utf-8')
    observed = guided.probe(workspace, job, tmp_path / 'probe')
    packed = guided.select(workspace, job['allowed_files'], seeds, observed, before)
    assert all(r['content_hash'] != seeds[0]['content_hash'] for r in packed['evidence'])
    assert next(r for r in packed['evidence'] if r['symbol'] == 'unused')['reason'] == 'retained_modified_function'
    guided.previous.repair.validate_evidence(workspace, job['allowed_files'], packed['evidence'])


def test_changed_harness_is_rejected_before_execution(case, tmp_path):
    workspace, job, _seeds = case
    p = __import__('pathlib').Path(job['harness']) / 'test_admission.py'
    p.write_text(p.read_text() + '\n# changed\n')
    with pytest.raises(ValueError, match='harness changed'):
        guided.probe(workspace, job, tmp_path / 'probe')


def test_scoped_strategy_restores_baseline_dependency_even_on_failure(case, tmp_path, monkeypatch):
    _workspace, job, _seeds = case
    original = guided.previous.refresh_seeds
    def fail(llm, job, events):
        assert guided.previous.refresh_seeds is not original
        raise RuntimeError('worker failed')
    monkeypatch.setattr(guided.guarded, 'run_candidate', fail)
    with pytest.raises(RuntimeError, match='worker failed'):
        guided.run_candidate(None, job, Events(tmp_path / 'trace.jsonl', 'test'))
    assert guided.previous.refresh_seeds is original


def test_comparison_denominator_keeps_worker_failures():
    rows = [{'policy': 'failure-context', 'accepted': False,
             'verification': {}, 'worker': {'metrics': None}, 'process': {'seconds': 600}}]
    result = comparison.summary(rows)
    assert result['failure-context']['tasks'] == result['failure-context']['missing_worker_results'] == 1
    assert result['failure-context']['passed'] == 0
