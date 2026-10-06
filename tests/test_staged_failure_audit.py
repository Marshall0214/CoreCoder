import hashlib
import json

import pytest

from docs.experiments.staged_failure_audit_v1 import delta, edit_provenance, validate_candidate


def fragment(start, end, content):
    return {'path': 'entry.py', 'start_line': start, 'end_line': end, 'content': content}


def test_docstring_gap_is_reconstruction_not_a_full_source_match():
    raw = b'def close():\n    """contract"""\n    return 1\n'
    edit = {'file': 'entry.py', 'old': 'def close():\n    return 1\n', 'new': 'replacement'}
    evidence = [fragment(1, 1, 'def close():\n'), fragment(3, 3, '    return 1\n')]
    row = edit_provenance(edit, {'entry.py': raw}, evidence, {'entry.py': [2]})
    assert row['old_full_matches'] == 0 and not row['old_in_single_fragment']
    assert row['matches_only_after_doc_removal']


def test_real_but_unshown_text_is_distinct_from_invented_text():
    source = {'entry.py': b'visible = 1\nhidden = 2\n'}
    evidence = [fragment(1, 1, 'visible = 1\n')]
    real = edit_provenance({'file': 'entry.py', 'old': 'hidden = 2', 'new': 'x'}, source, evidence, {})
    invented = edit_provenance({'file': 'entry.py', 'old': 'invented = 3', 'new': 'x'}, source, evidence, {})
    assert real['old_full_matches'] == 1 and not real['old_in_single_fragment']
    assert invented['old_full_matches'] == 0 and not invented['matches_only_after_doc_removal']


def test_visible_crlf_and_ambiguous_original_matches_are_recorded():
    source = {'entry.py': b'x = 1\r\nx = 1\r\n'}
    row = edit_provenance({'file': 'entry.py', 'old': 'x = 1', 'new': 'x = 2'}, source,
                          [fragment(1, 1, 'x = 1\r\n')], {})
    assert row['old_in_single_fragment'] and row['old_full_matches'] == 2


def test_evidence_delta_separates_documentation_loss_from_other_loss():
    source = {'entry.py': b'def prompt():\n    """doc"""\n    return 1\nextra = 2\n'}
    a = [fragment(1, 3, '')]
    b = [fragment(1, 1, ''), fragment(4, 4, '')]
    row = delta(source, a, b)[0]
    assert row['lost_docstring_lines'] == [2]
    assert row['lost_other_lines'] == [3]
    assert row['gained_other_lines'] == [4]


def test_probe_candidate_drift_is_rejected(tmp_path):
    raw = b'x = 1\n'
    path = tmp_path / 'entry.py'
    path.write_bytes(b'x = 2\n')
    evidence = [{**fragment(1, 1, raw.decode()), 'content_hash': hashlib.sha256(raw).hexdigest()}]
    response = json.dumps({'edits': [{'file': 'entry.py', 'old': 'x = 1', 'new': 'x = 2'}]})
    assert validate_candidate(tmp_path, {'entry.py': raw}, evidence, response, 'completed')
    path.write_bytes(b'x = 99\n')
    with pytest.raises(ValueError, match='differs'):
        validate_candidate(tmp_path, {'entry.py': raw}, evidence, response, 'completed')
