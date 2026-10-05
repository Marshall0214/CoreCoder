import hashlib

import pytest

from evals.linked_context import repack
from evals.runtime import Events
from evals.symbol_context import apply_symbol_patch, parse_source


def fixture(tmp_path):
    text = ('raise RuntimeError("never execute")\r\nclass TextType:\r\n'
            '    def convert(self, value): return str(value)\r\nTOKEN = TextType()\r\n'
            'def factory(flag_value):\r\n    if flag_value is None: return TOKEN\r\n    return TOKEN\r\n'
            'class Service:\r\n    def __init__(self, flag_value):\r\n'
            '        self.internal_flag_value = (flag_value is not None and (not False))\r\n'
            + '        padding = 1\r\n' * 20 + '        self.kind = factory(flag_value)\r\n')
    (tmp_path / 'module.py').write_bytes(text.encode())
    info = parse_source('module.py', text.encode(), {})
    rows = []
    for symbol, reason in [('Service.__init__', 'keyword'), ('factory', 'static-reference')]:
        a, b, _ = info['symbols'][symbol]
        end = a if reason == 'keyword' else b
        rows.append({'path': 'module.py', 'symbol': symbol, 'start_line': a, 'end_line': end,
                     'symbol_range': [a, b], 'complete_symbol': end == b,
                     'content_hash': hashlib.sha256(text.encode()).hexdigest(),
                     'content': ''.join(info['lines'][a - 1:end]), 'reason': reason, 'depth': 0,
                     'parse_status': 'valid'})
    return text, rows


def test_linked_packing_includes_assignment_and_atomic_alias_chain(tmp_path):
    text, base = fixture(tmp_path)
    rows = repack(tmp_path, 'flag_value', ['module.py'], base, Events(tmp_path / 'trace.jsonl', 'linked'), 1200)
    assignment = next(row for row in rows if row['reason'] == 'query-assignment-window')
    assert 'self.kind = factory(flag_value)' in assignment['content']
    assert not assignment['complete_symbol']
    assert {'factory', 'TextType', '<module-binding>'} <= {row['symbol'] for row in rows}
    assert all(row['content'].endswith('\r\n') for row in rows)
    assert sum(len(row['content']) for row in rows) <= 1200
    for index, row in enumerate(rows):
        assert not any(other['path'] == row['path'] and other['start_line'] <= row['end_line']
                       and row['start_line'] <= other['end_line'] for other in rows[:index])
    again = repack(tmp_path, 'flag_value', ['module.py'], base, Events(tmp_path / 'again.jsonl', 'again'), 1200)
    assert again == rows and (tmp_path / 'module.py').read_bytes() == text.encode()


def test_budget_never_retains_only_part_of_alias_bundle(tmp_path):
    _, base = fixture(tmp_path)
    rows = repack(tmp_path, 'flag_value', ['module.py'], base, Events(tmp_path / 'trace.jsonl', 'small'), 256)
    assert sum(len(row['content']) for row in rows) <= 256
    assert not any(row['symbol'] == '<module-binding>' for row in rows)


def test_repacked_context_keeps_unshown_text_and_version_guards(tmp_path):
    import json

    text, base = fixture(tmp_path)
    rows = repack(tmp_path, 'flag_value', ['module.py'], base, Events(tmp_path / 'trace.jsonl', 'guard'), 1200)
    patch = json.dumps({'edits': [{'file': 'module.py', 'old': 'raise RuntimeError("never execute")', 'new': 'pass'}]})
    with pytest.raises(ValueError, match='not supplied'):
        apply_symbol_patch(patch, tmp_path, ['module.py'], rows)
    (tmp_path / 'module.py').write_bytes((text + '# changed\r\n').encode())
    with pytest.raises(ValueError, match='version changed'):
        repack(tmp_path, 'flag_value', ['module.py'], base, Events(tmp_path / 'stale.jsonl', 'stale'), 1200)
