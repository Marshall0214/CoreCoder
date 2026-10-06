import hashlib
import json

import pytest

from docs.experiments import function_index_audit_v1 as experiment
from evals.runner import digest, snapshot
from evals.symbol_index import PythonCodeIndex


def build(tmp_path, files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    allowed = [p for p in files if p.startswith('src/')]
    index = experiment.FunctionIndex(tmp_path, allowed)
    metadata = index.refresh()
    return index, metadata


def test_corpus_contains_exact_decorated_functions_not_hidden_or_nonfunction_code(tmp_path):
    source = 'secret = 1\r\nraise RuntimeError("must not execute")\r\nclass Service:\r\n    label = "needle"\r\n    @decorate\r\n    async def needle(self):\r\n        return 1\r\n'
    index, metadata = build(tmp_path, {'src/service.py': source,
                                     'tests/hidden.py': 'def needle_secret():\n    pass\n',
                                     'readme.md': 'needle secret'})
    assert metadata['files'] == 1 and metadata['chunks'] == 1
    assert index.chunks[0].content == ''.join(source.splitlines(keepends=True)[4:])
    assert index.names[('src/service.py', 5, 7)] == 'Service.needle'
    assert index.chunks[0].content_hash == hashlib.sha256(source.encode()).hexdigest()
    assert not index.rank('secret')


def test_ranking_is_deterministic_and_source_changes_invalidate_identity(tmp_path):
    index, original = build(tmp_path, {'src/a.py': 'def needle():\n    return 1\n',
                                     'src/b.py': 'def needle():\n    return 1\n'})
    ranked = index.rank('needle')
    assert [c.path for _, c in ranked] == ['src/a.py', 'src/b.py']
    assert ranked == index.rank('needle')
    (tmp_path / 'src/a.py').write_text('def changed():\n    return 2\n')
    assert index.refresh()['index_hash'] != original['index_hash']
    assert [c.path for _, c in index.rank('changed')] == ['src/a.py']


def test_index_rejects_source_mutation_between_ast_index_and_evidence(tmp_path, monkeypatch):
    original = PythonCodeIndex.refresh

    def mutate(index):
        metadata = original(index)
        (tmp_path / 'src/a.py').write_text('def needle():\n    return 2\n')
        return metadata

    monkeypatch.setattr(PythonCodeIndex, 'refresh', mutate)
    with pytest.raises(ValueError, match='Source changed'):
        build(tmp_path, {'src/a.py': 'def needle():\n    return 1\n'})


def test_parse_failure_is_explicit_not_silently_indexed_as_function(tmp_path):
    index, metadata = build(tmp_path, {'src/broken.py': 'def needle(:\n    pass\n'})
    assert metadata['parse_failures'] == ['src/broken.py'] and index.chunks == []
    assert experiment.pack(index, index.rank('needle'))['evidence'] == []


def test_oversized_function_skipped_without_truncation_and_nested_overlap_not_repeated(tmp_path):
    index, _ = build(tmp_path, {'src/a.py': 'def needle():\n' + '    value = 1\n' * 100,
                              'src/b.py': 'def needle():\n    def inner():\n        return 1\n    return inner()\n'})
    packed = experiment.pack(index, index.rank('needle inner'), limit=150)
    assert packed['metadata']['evidence_chars'] <= 150
    assert len(packed['evidence']) == 1
    assert packed['evidence'][0]['content'] in (tmp_path / 'src/b.py').read_text()
    assert packed['evidence'][0]['complete_symbol']
    assert {r['reason'] for r in packed['metadata']['discarded']} == {'budget', 'overlap'}


def test_one_hop_dependencies_preserve_seeds_and_budget(tmp_path):
    index, _ = build(tmp_path, {'src/pkg/entry.py': 'from .helper import normalize\ndef needle(v):\n    return normalize(v)\n',
                              'src/pkg/helper.py': 'from .other import second\ndef normalize(v):\n    return second(v)\n',
                              'src/pkg/other.py': 'def second(v):\n    return bool(v)\n'})
    ranked = index.rank('needle')
    seeds = experiment.pack(index, ranked)
    expanded = experiment.pack(index, ranked, depth=1)
    assert expanded['evidence'][:1] == seeds['evidence']
    assert [(r['path'], r['symbol']) for r in expanded['evidence']] == [
        ('src/pkg/entry.py', 'needle'), ('src/pkg/helper.py', 'normalize')]
    bounded = experiment.pack(index, ranked, depth=1, limit=seeds['metadata']['evidence_chars'])
    assert bounded['evidence'] == seeds['evidence']


def test_all_public_evidence_frozen_before_reference_scoring(tmp_path, monkeypatch):
    cases, bundles, priors = [], [], []
    for name in ('one', 'two'):
        workspace = tmp_path / name / 'before'
        index, _ = build(workspace, {'src/a.py': 'def needle():\n    return 1\n',
                                     'tests/hidden.py': 'target_secret'})
        rows = experiment.pack(index, index.rank('needle'))
        cases.append({'task_id': name, 'before': workspace, 'before_hash': digest(snapshot(workspace)),
                      'description': 'needle', 'allowed_files': ['src/a.py']})
        bundles.append({'task_id': name, 'policies': {'raw-chunks': rows, 'functions': rows}})
        priors.append({'task_id': name, 'query': 'needle contract contracts'})
    output = tmp_path / 'report'

    def labels(_):
        observations = json.loads((output / 'observations.json').read_text())
        assert len(observations) == 2
        assert 'target_secret' not in json.dumps(observations)
        assert all('scores' not in r for r in observations)
        assert all(r['index']['source_hash'] == r['line_index']['source_hash'] for r in observations)
        assert all('python-line-chunks' in r['policies'] for r in observations)
        return ['src/a.py'], [{'path': 'src/a.py', 'start_line': 2, 'end_line': 2}]

    monkeypatch.setattr(experiment.audit, 'labels', labels)
    result = experiment.evaluate(cases, bundles, priors, output)
    assert result['complete'] and result['repair_llm_calls'] == result['embedding_calls'] == 0
    assert result['summary']['direct-functions']['changed_line_recall'] == 1
    with pytest.raises(ValueError, match='fresh output'):
        experiment.evaluate(cases, bundles, priors, output)
