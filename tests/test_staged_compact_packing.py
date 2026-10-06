import hashlib
import json

import pytest

from docs.experiments.staged_compact_packing_v1 import compact_evidence, comparison, docstring_ranges
from evals.symbol_context import apply_symbol_patch


def candidate(raw, start, end):
    return {'path': 'entry.py', 'start_line': start, 'end_line': end,
            'content_hash': hashlib.sha256(raw).hexdigest(),
            'content': ''.join(raw.decode('utf-8').splitlines(keepends=True)[start - 1:end]),
            'reason': 'exploration_read'}


def test_compaction_keeps_both_functions_within_same_cap_and_preserves_provenance():
    raw = ('def prompt():\n    """' + 'documentation ' * 30 + '"""\n    return 1\n'
           'def confirm():\n    """' + 'documentation ' * 30 + '"""\n    return 2\n').encode()
    pool = {'reads': [candidate(raw, 1, 3)], 'seeds': [candidate(raw, 4, 6)]}
    before = json.dumps(pool, sort_keys=True)
    result = comparison('prompt or confirm', {'entry.py': raw}, pool, 500, ('prompt', 'confirm'))
    assert {a['name'] for a in result['coverage'] if a['compact_lines'] == a['non_docstring_lines']} == {'prompt', 'confirm'}
    assert not all(a['baseline_lines'] == a['non_docstring_lines'] for a in result['coverage'])
    assert result['compact']['selected_chars'] <= 500
    assert json.dumps(pool, sort_keys=True) == before
    for row in result['fragments']:
        assert row['content'] == candidate(raw, row['start_line'], row['end_line'])['content']
        assert row['content_hash'] == hashlib.sha256(raw).hexdigest()


def test_overlap_is_counted_once_and_unseen_source_is_never_added():
    raw = b'a = 1\nb = 2\nc = 3\nunseen = 4\n'
    rows, _ = compact_evidence([candidate(raw, 1, 2)], [candidate(raw, 2, 3)], {'entry.py': raw}, 100)
    assert ''.join(row['content'] for row in rows) == 'a = 1\nb = 2\nc = 3\n'
    assert [(r['start_line'], r['end_line']) for r in rows] == [(1, 2), (3, 3)]


def test_partial_docstring_is_retained_and_runtime_strings_are_not_removed():
    raw = b'def prompt():\n    """first\n    last"""\n    x = "runtime"\n    return x\n'
    rows, details = compact_evidence([candidate(raw, 1, 2), candidate(raw, 4, 5)], [], {'entry.py': raw}, 1000)
    assert details['removed_docstring_lines']['entry.py'] == []
    assert '"""first' in rows[0]['content'] and '"runtime"' in rows[1]['content']


@pytest.mark.parametrize('raw', [b'def prompt(): "doc"; return 1\n', b'"module doc"; x = 1\n'])
def test_docstrings_sharing_lines_with_executable_code_are_retained(raw):
    assert docstring_ranges(raw)[0] == []
    rows, _ = compact_evidence([candidate(raw, 1, 1)], [], {'entry.py': raw}, 1000)
    assert rows[0]['content'] == raw.decode()


def test_budget_rejects_whole_compacted_candidate_instead_of_truncating_code():
    raw = b'def prompt():\n    """doc"""\n    return 1\n'
    rows, details = compact_evidence([candidate(raw, 1, 3)], [], {'entry.py': raw}, 14)
    assert rows == [] and details['decisions'][0]['decision'] == 'remaining_capacity'


@pytest.mark.parametrize('corruption', ['version', 'content', 'range'])
def test_forged_candidate_is_rejected(corruption):
    raw = b'real = 1\n'
    row = candidate(raw, 1, 1)
    if corruption == 'version':
        row['content_hash'] = 'old'
    elif corruption == 'content':
        row['content'] = 'invented = 1\n'
    else:
        row['end_line'] = 2
    with pytest.raises(ValueError, match='mismatch'):
        compact_evidence([row], [], {'entry.py': raw}, 1000)


def test_split_crlf_evidence_allows_visible_edit_and_rejects_edit_across_removed_gap(tmp_path):
    raw = b'def prompt():\r\n    """doc"""\r\n    return 1\r\n'
    path = tmp_path / 'entry.py'
    path.write_bytes(raw)
    evidence, _ = compact_evidence([candidate(raw, 1, 3)], [], {'entry.py': raw}, 1000)
    assert len(evidence) == 2 and '\r\n' in evidence[0]['content']
    across = json.dumps({'edits': [{'file': 'entry.py', 'old': '    """doc"""', 'new': '    pass'}]})
    with pytest.raises(ValueError, match='not supplied'):
        apply_symbol_patch(across, tmp_path, ['entry.py'], evidence)
    assert path.read_bytes() == raw
    visible = json.dumps({'edits': [{'file': 'entry.py', 'old': 'return 1', 'new': 'return 2'}]})
    assert apply_symbol_patch(visible, tmp_path, ['entry.py'], evidence) == ['entry.py']
    assert path.read_bytes() == raw.replace(b'return 1', b'return 2')


def test_syntax_error_retains_all_candidate_text():
    raw = b'def broken(\n    """uncertain doc"""\n'
    rows, details = compact_evidence([candidate(raw, 1, 2)], [], {'entry.py': raw}, 1000)
    assert rows[0]['content'] == raw.decode()
    assert details['parse_status']['entry.py'] == 'syntax-error-retained'


def test_unicode_ast_offsets_and_determinism():
    raw = 'def prompt():\n    """中文文档"""\n    return "中文值"\n'.encode()
    args = ([candidate(raw, 1, 3)], [], {'entry.py': raw}, 1000)
    first = compact_evidence(*args)
    assert first == compact_evidence(*args)
    assert '中文文档' not in ''.join(row['content'] for row in first[0])
    assert '中文值' in ''.join(row['content'] for row in first[0])
