import hashlib
import json
from types import SimpleNamespace

import pytest

from docs.experiments import model_source_selection_v1 as selection
from docs.experiments.function_index_repair_v1 import validate_evidence
from evals.runtime import Events


def sources(tmp_path):
    (tmp_path / 'code.py').write_text('class Client:\n    def __init__(self, timeout):\n        self.timeout = timeout\n'
                                     '    def send(self):\n        """Send with the configured timeout."""\n'
                                     '        return self.timeout\n', encoding='utf-8')
    return selection.inventory(tmp_path, ['code.py'])


def test_inventory_preserves_source_hash_and_methods(tmp_path):
    rows = sources(tmp_path)
    assert [r['symbol'] for r in rows] == ['Client.__init__', 'Client.send']
    evidence = selection.pack(rows, [rows[1]['id'], rows[0]['id']])
    validate_evidence(tmp_path, ['code.py'], evidence)
    assert evidence[0]['content_hash'] == hashlib.sha256((tmp_path / 'code.py').read_bytes()).hexdigest()
    assert any('configured timeout' in r['doc'] for r in selection.overview(rows, 'timeout', []))


@pytest.mark.parametrize('ids', [[], ['missing'], ['code.py:Client.send'] * 2, [1]])
def test_selection_rejects_invalid_ids(tmp_path, ids):
    with pytest.raises(ValueError):
        selection.pack(sources(tmp_path), ids)


def test_inventory_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        selection.inventory(tmp_path, ['../outside.py'])


def test_refresh_tracks_changed_line_ranges(tmp_path):
    rows = sources(tmp_path)
    seed = selection.pack(rows, [rows[1]['id']])
    p = tmp_path / 'code.py'
    p.write_text('\n' + p.read_text(), encoding='utf-8')
    fresh = selection.refresh(tmp_path, ['code.py'], seed)
    assert fresh[0]['start_line'] == seed[0]['start_line'] + 1
    validate_evidence(tmp_path, ['code.py'], fresh)


def test_selection_requests_only_original_metadata(tmp_path):
    rows = sources(tmp_path)
    events = Events(tmp_path / 'trace.jsonl', 'test')
    seen = []

    class Model:
        def chat(self, messages, tools):
            seen.append(messages)
            return SimpleNamespace(content=json.dumps({'symbols': [rows[1]['id']]}), tool_calls=[])

    evidence = selection.select(Model(), {'workspace': str(tmp_path), 'allowed_files': ['code.py'],
                                         'description': 'timeout defect', 'evidence': []}, events)
    payload = json.loads(seen[0][1]['content'])
    assert set(payload) == {'description', 'symbols'}
    assert all(set(r) == {'id', 'signature', 'doc'} for r in payload['symbols'])
    validate_evidence(tmp_path, ['code.py'], evidence)


def test_long_symbol_is_bounded_on_line_boundaries(tmp_path):
    (tmp_path / 'long.py').write_text('def f():\n' + '    x = 1\n' * 900, encoding='utf-8')
    rows = selection.inventory(tmp_path, ['long.py'])
    evidence = selection.pack(rows, ['long.py:f'])
    assert len(evidence[0]['content']) <= 6000 and not evidence[0]['complete_symbol']
    validate_evidence(tmp_path, ['long.py'], evidence)
