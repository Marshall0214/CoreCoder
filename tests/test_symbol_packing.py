import json

import pytest

from evals.runtime import Events
from evals.symbol_context import apply_symbol_patch, symbol_evidence


def select(tmp_path, policy, depth=1):
    # The entry fits the total budget but needs a partial window under reservation.
    # The dependency call is within that window; unrelated code stays out of retrieval.
    files = {'entry.py': 'from helper import normalize\n'
             'def needle(value):\n    return normalize(value)\n' + '    value = value\n' * 45,
             'noise.py': 'def unrelated():\n' + '    value = 1\n' * 40,
             'helper.py': 'raise RuntimeError("never execute")\n'
             'def normalize(value):\n' + '    value = value\n' * 33 + '    return bool(value)\n'}
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    events = Events(tmp_path / (policy + '.jsonl'), policy)
    rows = symbol_evidence(tmp_path, 'needle', list(files), events, max_chars=1400, top_k=2,
                           index_mode='symbols', packing_policy=policy, depth=depth)
    return rows, json.loads(events.path.read_text())


def test_reserved_budget_admits_dependency_and_preserves_partial_patch_guard(tmp_path):
    rows, trace = select(tmp_path, 'dependency-reserve')
    assert trace['seed_limit'] == 700 and trace['seed_chars'] <= 700
    assert trace['evidence_chars'] <= 1400
    assert any(row['symbol'] == 'normalize' and row['depth'] == 1 for row in rows)
    greedy, _ = select(tmp_path, 'seed-first')
    assert not any(row['symbol'] == 'normalize' for row in greedy)
    entry = next(row for row in rows if row['symbol'] == 'needle')
    assert not entry['complete_symbol'] and entry['content'].endswith('\n')
    assert entry['symbol_range'][1] > entry['end_line']
    patch = json.dumps({'edits': [{'file': 'entry.py', 'old': (tmp_path / 'entry.py').read_text(), 'new': 'pass\n'}]})
    before = (tmp_path / 'entry.py').read_bytes()
    with pytest.raises(ValueError, match='not supplied'):
        apply_symbol_patch(patch, tmp_path, ['entry.py'], rows)
    assert (tmp_path / 'entry.py').read_bytes() == before


def test_dependency_beyond_displayed_window_is_not_discovered(tmp_path):
    files = {'entry.py': 'from helper import normalize\ndef needle(value):\n'
             + '    value = value\n' * 60 + '    return normalize(value)\n',
             'helper.py': 'def normalize(value):\n    return bool(value)\n'}
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    events = Events(tmp_path / 'trace.jsonl', 'partial')
    rows = symbol_evidence(tmp_path, 'needle', list(files), events, max_chars=1400, top_k=1,
                           index_mode='symbols', packing_policy='dependency-reserve')
    assert rows and not rows[0]['complete_symbol']
    assert 'normalize(value)' not in rows[0]['content']
    assert not any(row['symbol'] == 'normalize' for row in rows)
    assert json.loads(events.path.read_text())['dependency_edges'] == []


def test_seed_first_retains_original_budget_and_depth_zero_disables_reserve(tmp_path):
    _, original = select(tmp_path, 'seed-first')
    assert original['seed_limit'] == 1400
    _, no_dependencies = select(tmp_path, 'dependency-reserve', depth=0)
    assert no_dependencies['seed_limit'] == 1400
    assert no_dependencies['dependency_chars'] == 0


def test_policy_validation_and_unused_reserve_is_not_backfilled(tmp_path):
    (tmp_path / 'a.py').write_text('def needle():\n    return 1\n')
    events = Events(tmp_path / 'trace.jsonl', 'reserve')
    rows = symbol_evidence(tmp_path, 'needle', ['a.py'], events, max_chars=256,
                           packing_policy='dependency-reserve')
    trace = json.loads(events.path.read_text())
    assert len(rows) == 1 and trace['seed_limit'] == 128 and trace['dependency_chars'] == 0
    with pytest.raises(ValueError, match='packing policy'):
        symbol_evidence(tmp_path, 'needle', ['a.py'], events, packing_policy='unknown')
