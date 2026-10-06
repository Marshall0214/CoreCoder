import copy
import hashlib
import json

import pytest

from docs.experiments.staged_containment_packing_v1 import containment_evidence
from evals.staged_repair import select_evidence
from evals.symbol_context import apply_symbol_patch


def row(start, end, text):
    return {'path': 'entry.py', 'start_line': start, 'end_line': end, 'content_hash': 'source', 'content': text}


def test_contained_fragment_frees_space_for_later_candidate():
    reads = [row(1, 3, 'a\nb\nc\n')]
    seeds = [row(2, 2, 'b\n'), row(4, 4, 'd\n')]
    assert select_evidence(reads, seeds, 8) == reads + seeds[:1]
    selected, audit = containment_evidence(reads, seeds, 8)
    assert selected == reads + seeds[1:]
    assert audit['decisions'][1]['decision'] == 'single_fragment_contained'


def test_union_coverage_does_not_remove_continuous_edit_anchor():
    reads = [row(1, 1, 'a\n'), row(2, 2, 'b\n')]
    seed = row(1, 2, 'a\nb\n')
    selected, _ = containment_evidence(reads, [seed], 20)
    assert selected == reads + [seed]


def test_partial_overlap_is_preserved_whole_and_pool_is_unchanged():
    reads, seeds = [row(1, 2, 'a\nb\n')], [row(2, 3, 'b\nc\n')]
    original = copy.deepcopy((reads, seeds))
    selected, _ = containment_evidence(reads, seeds, 20)
    assert selected == reads + seeds and (reads, seeds) == original
    assert containment_evidence(reads, seeds, 20)[0] == selected


def test_budget_rejected_fragment_cannot_shadow_a_later_candidate():
    big, small = row(1, 3, 'a\nb\nc\n'), row(2, 2, 'b\n')
    selected, _ = containment_evidence([big], [small], 2)
    assert selected == [small]


def test_line_ending_difference_prevents_nonexact_containment():
    parent, child = row(1, 2, 'a\nb'), row(2, 2, 'b\r\n')
    selected, _ = containment_evidence([parent], [child], 20)
    assert selected == [parent, child]


def test_normalized_read_with_terminal_empty_source_line_is_accepted():
    candidate = row(1, 3, 'a\nb\n')
    selected, _ = containment_evidence([candidate], [], 20)
    assert selected == [candidate]


def test_mixed_source_versions_are_rejected():
    other = {**row(2, 2, 'b\n'), 'content_hash': 'changed'}
    with pytest.raises(ValueError, match='versions'):
        containment_evidence([row(1, 2, 'a\nb\n')], [other], 20)


def test_docstrings_and_crlf_contiguous_patch_remain_available(tmp_path):
    raw = b'def close():\r\n    """contract"""\r\n    return 1\r\n'
    (tmp_path / 'entry.py').write_bytes(raw)
    parent = {**row(1, 3, raw.decode()), 'content_hash': hashlib.sha256(raw).hexdigest()}
    child = {**row(3, 3, '    return 1\r\n'), 'content_hash': parent['content_hash']}
    evidence, _ = containment_evidence([parent], [child], 1000)
    assert evidence == [parent]
    patch = json.dumps({'edits': [{'file': 'entry.py', 'old': '"""contract"""', 'new': '"""kept contract"""'}]})
    assert apply_symbol_patch(patch, tmp_path, ['entry.py'], evidence) == ['entry.py']
    assert (tmp_path / 'entry.py').read_bytes() == raw.replace(b'contract', b'kept contract')
