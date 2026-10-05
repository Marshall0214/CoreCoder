import hashlib
import json

import pytest

from corecoder.retrieval.keyword import KeywordIndex
from evals.runtime import Events
from evals.symbol_context import apply_symbol_patch, symbol_evidence


def build(tmp_path, files, query='needle', **kwargs):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode('utf-8'))
    return symbol_evidence(tmp_path, query, list(files), Events(tmp_path / 'trace.jsonl', 'test'), **kwargs)


def test_large_file_selects_complete_decorated_async_method_with_exact_crlf(tmp_path):
    source = '# unrelated\r\n' * 200 + 'class Service:\r\n    @decorate\r\n    async def needle(self):\r\n        return 1\r\n'
    rows = build(tmp_path, {'service.py': source}, max_chars=256, top_k=1)
    assert len(rows) == 1 and rows[0]['symbol'] == 'Service.needle'
    assert rows[0]['complete_symbol'] and rows[0]['start_line'] == 202
    assert rows[0]['content'] == '    @decorate\r\n    async def needle(self):\r\n        return 1\r\n'
    assert rows[0]['content_hash'] == hashlib.sha256(source.encode()).hexdigest()


@pytest.mark.parametrize('statement,call', [('from .helper import normalize as convert', 'convert(value)'),
                                         ('from . import helper as h', 'h.normalize(value)')])
def test_local_alias_dependency_expansion_never_executes_modules(tmp_path, statement, call):
    files = {'src/pkg/entry.py': f'{statement}\ndef needle(value):\n    return {call}\n',
             'src/pkg/helper.py': 'raise RuntimeError("must not import")\ndef normalize(value):\n    return bool(value)\n'}
    rows = build(tmp_path, files, top_k=1, depth=1)
    assert [(row['path'], row['symbol']) for row in rows] == [
        ('src/pkg/entry.py', 'needle'), ('src/pkg/helper.py', 'normalize')]
    assert rows[1]['reason'] == 'static-reference' and rows[1]['depth'] == 1


def test_dependency_cycles_and_overlapping_seeds_do_not_duplicate_text(tmp_path):
    rows = build(tmp_path, {'module.py': 'def needle():\n    return helper()\n\ndef helper():\n    return needle()\n'},
                 top_k=2, depth=3)
    assert len(rows) == 2 and {row['symbol'] for row in rows} == {'needle', 'helper'}
    assert len({(row['path'], row['start_line'], row['end_line']) for row in rows}) == len(rows)


def test_oversized_symbol_is_marked_partial_without_midline_truncation(tmp_path):
    source = 'def needle():\n' + '    value = 1\n' * 100 + '    return value\n'
    rows = build(tmp_path, {'module.py': source}, max_chars=600, top_k=1)
    assert rows and not rows[0]['complete_symbol']
    assert rows[0]['symbol_range'] == [1, 102]
    assert rows[0]['end_line'] == 40
    assert rows[0]['content'].endswith('\n')
    assert sum(len(row['content']) for row in rows) <= 600


def test_unparseable_source_has_explicit_window_status(tmp_path):
    rows = build(tmp_path, {'broken.py': 'def needle(:\n    pass\n'}, top_k=1)
    assert rows[0]['parse_status'] == 'syntax-error-window'
    assert not rows[0]['complete_symbol']


def test_index_version_change_is_rejected_before_evidence_delivery(tmp_path, monkeypatch):
    original = KeywordIndex.rank

    def mutate(index, query):
        ranked = original(index, query)
        (tmp_path / 'module.py').write_text('def needle():\n    return 2\n')
        return ranked

    monkeypatch.setattr(KeywordIndex, 'rank', mutate)
    with pytest.raises(ValueError, match='version changed'):
        build(tmp_path, {'module.py': 'def needle():\n    return 1\n'})


def test_partial_patch_rejects_unseen_edit_atomically(tmp_path):
    rows = build(tmp_path, {'module.py': 'secret = 1\n\ndef needle():\n    return 1\n'}, top_k=1)
    before = (tmp_path / 'module.py').read_bytes()
    patch = {'edits': [{'file': 'module.py', 'old': 'return 1', 'new': 'return 2'},
                       {'file': 'module.py', 'old': 'secret = 1', 'new': 'secret = 2'}]}
    with pytest.raises(ValueError, match='not supplied'):
        apply_symbol_patch(json.dumps(patch), tmp_path, ['module.py'], rows)
    assert (tmp_path / 'module.py').read_bytes() == before
    changed = apply_symbol_patch(json.dumps({'edits': patch['edits'][:1]}), tmp_path, ['module.py'], rows)
    assert changed == ['module.py']


def test_local_patch_rejects_stale_full_file_even_when_fragment_unchanged(tmp_path):
    rows = build(tmp_path, {'module.py': 'secret = 1\n\ndef needle():\n    return 1\n'}, top_k=1)
    (tmp_path / 'module.py').write_text('secret = 2\n\ndef needle():\n    return 1\n')
    with pytest.raises(ValueError, match='version changed'):
        apply_symbol_patch(json.dumps({'edits': [{'file': 'module.py', 'old': 'return 1', 'new': 'return 2'}]}),
                           tmp_path, ['module.py'], rows)
