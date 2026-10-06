import pytest

from docs.experiments.public_coverage_followup_v1 import coverage, missing_ranges
from tests.test_staged_evidence_coverage import fragment


def test_missing_ranges_keep_disjoint_holes():
    assert missing_ranges(1, 8, {2, 3, 5, 8}) == [[1, 1], [4, 4], [6, 7]]
    assert missing_ranges(1, 2, {1, 2}) == []


def test_full_definition_in_pool_but_not_visible_is_packing_gap():
    sources = {'entry.py': 'def prompt():\n    pass\ndef confirm():\n    pass\n'}
    pool = {'reads': [fragment(1, 2, 'aaaa')], 'seeds': [fragment(3, 4, 'bbbb')]}
    result = coverage('prompt and confirm', sources, pool, 4, ('prompt', 'confirm'))
    rows = {a['name']: a for a in result['definition_anchors']}
    assert rows['prompt']['gap_stage'] == 'none'
    assert rows['confirm']['gap_stage'] == 'packing'
    assert rows['confirm']['pool_missing_ranges'] == []
    assert rows['confirm']['visible_missing_ranges'] == [[3, 4]]


def test_acquisition_and_packing_gaps_can_coexist():
    sources = {'entry.py': 'def prompt():\n    first()\n    second()\n'}
    pool = {'reads': [fragment(1, 1, 'aaaa')], 'seeds': [fragment(2, 2, 'bbbb')]}
    row = coverage('prompt', sources, pool, 4, ('prompt',))['definition_anchors'][0]
    assert row['gap_stage'] == 'mixed'
    assert row['gap_stages'] == ['acquisition', 'packing']
    assert row['pool_missing_ranges'] == [[3, 3]]
    assert row['visible_missing_ranges'] == [[2, 3]]


def test_lexical_coverage_without_named_api_has_no_semantic_success_claim():
    sources = {'entry.py': 'def resolve():\n    return flag_value\n'}
    pool = {'reads': [fragment(1, 2, 'ok')], 'seeds': []}
    result = coverage('Preserve flag_value and conversion.', sources, pool, 10)
    assert result['definition_anchors'] == []
    assert result['summary']['fully_visible'] == 1
    assert 'not necessary repair locations' in result['limitations']


def test_bare_anchor_must_come_from_public_problem():
    with pytest.raises(ValueError, match='verbatim'):
        coverage('Repair conversion.', {'entry.py': 'def oracle():\n    pass\n'}, {'reads': [], 'seeds': []}, 10, ('oracle',))
