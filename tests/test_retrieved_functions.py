import hashlib
import json

import pytest

from corecoder.retrieval.keyword import KeywordIndex
from docs.experiments.retrieved_functions_v1 import evidence
from evals.symbol_context import apply_symbol_patch


def frozen(tmp_path, files, seed_path):
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode())
    index = KeywordIndex(tmp_path, list(files))
    metadata = index.refresh()
    chunk = next(c for c in index.chunks if c.path == seed_path)
    row = {k: getattr(chunk, k) for k in ('path', 'start_line', 'end_line', 'content_hash')}
    return {'index': metadata, 'chunk_rankings': {'bm25': [row]}}


def test_complete_decorated_method_preserves_source_and_version(tmp_path):
    text = 'class Service:\r\n    @decorate\r\n    async def needle(self):\r\n        return 1\r\n'
    observation = frozen(tmp_path, {'service.py': text}, 'service.py')
    rows, metadata = evidence(tmp_path, ['service.py'], observation)
    assert len(rows) == 1 and rows[0]['symbol'] == 'Service.needle'
    assert rows[0]['content'] == ''.join(text.splitlines(keepends=True)[1:])
    assert rows[0]['content_hash'] == hashlib.sha256(text.encode()).hexdigest()
    assert metadata['evidence_chars'] == len(rows[0]['content'])


def test_dependency_is_local_one_hop_without_module_execution(tmp_path):
    files = {'src/pkg/entry.py': 'from .helper import normalize\ndef needle(value):\n    return normalize(value)\n',
             'src/pkg/helper.py': 'raise RuntimeError("must not execute")\ndef normalize(value):\n    return second(value)\n',
             'src/pkg/second.py': 'def second(value):\n    return bool(value)\n'}
    observation = frozen(tmp_path, files, 'src/pkg/entry.py')
    rows, metadata = evidence(tmp_path, list(files), observation)
    assert [(r['path'], r['symbol']) for r in rows] == [
        ('src/pkg/entry.py', 'needle'), ('src/pkg/helper.py', 'normalize')]
    assert rows[1]['reason'] == 'static_function_dependency'
    assert metadata['dependency_depth'] == 1


def test_oversized_function_uses_exact_chunk_and_hard_budget(tmp_path):
    text = 'def needle():\n' + '    value = 1\n' * 100 + '    return value\n'
    observation = frozen(tmp_path, {'module.py': text}, 'module.py')
    rows, metadata = evidence(tmp_path, ['module.py'], observation, limit=600)
    assert len(rows) == 1 and rows[0]['symbol'] is None
    assert rows[0]['reason'] == 'raw_chunk_fallback'
    assert rows[0]['content'] == '\n'.join(text.splitlines()[:40])
    assert metadata['evidence_chars'] <= 600 and metadata['rejected']
    rows, metadata = evidence(tmp_path, ['module.py'], observation, limit=10)
    assert rows == [] and metadata['evidence_chars'] == 0


def test_stale_corpus_and_forged_citation_are_rejected(tmp_path):
    observation = frozen(tmp_path, {'module.py': 'def needle():\n    return 1\n'}, 'module.py')
    observation['chunk_rankings']['bm25'][0]['end_line'] = 100
    with pytest.raises(ValueError, match='citation'):
        evidence(tmp_path, ['module.py'], observation)
    (tmp_path / 'module.py').write_text('def needle():\n    return 2\n')
    with pytest.raises(ValueError, match='corpus changed'):
        evidence(tmp_path, ['module.py'], observation)


def test_nested_function_dedup_and_unseen_patch_rejection(tmp_path):
    text = 'secret = 1\ndef needle():\n    def inner():\n        return 1\n    return inner()\n'
    observation = frozen(tmp_path, {'module.py': text}, 'module.py')
    rows, _ = evidence(tmp_path, ['module.py'], observation)
    assert len(rows) == 1 and rows[0]['symbol'] == 'needle'
    patch = {'edits': [{'file': 'module.py', 'old': 'return 1', 'new': 'return 2'},
                       {'file': 'module.py', 'old': 'secret = 1', 'new': 'secret = 2'}]}
    with pytest.raises(ValueError, match='not supplied'):
        apply_symbol_patch(json.dumps(patch), tmp_path, ['module.py'], rows)
    assert (tmp_path / 'module.py').read_text() == text
