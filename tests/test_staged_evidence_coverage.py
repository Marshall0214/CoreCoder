from docs.experiments.staged_evidence_coverage_v1 import diagnose, public_anchors


def fragment(start, end, content, reason='exploration_read'):
    return {'path': 'entry.py', 'start_line': start, 'end_line': end,
            'content': content, 'content_hash': 'source', 'reason': reason}


def test_public_names_resolve_owner_and_exclude_prose():
    sources = {'entry.py': 'class Context:\n    def invoke(self):\n        pass\n'
                          'class Other:\n    def invoke(self):\n        pass\n'}
    anchors = public_anchors('Context.invoke preserves explicit arguments.', sources)
    assert {row['name'] for row in anchors} == {'Context.invoke'}
    assert public_anchors('Repair callback ordering.', sources) == []


def test_selection_loss_is_distinct_from_partial_acquisition():
    source = {'entry.py': 'def prompt():\n    first()\n    second()\n'}
    pool = {'reads': [fragment(1, 1, 'aaaa')], 'seeds': [fragment(2, 2, 'bbbb')]}
    read = diagnose('prompt', source, pool, 4, 'read-first', ('prompt',))['anchors'][0]
    seed = diagnose('prompt', source, pool, 4, 'seed-first', ('prompt',))['anchors'][0]
    assert read['pool_partial'] and read['pool_lines'] == 2
    assert read['selection_lost_lines'] == seed['selection_lost_lines'] == 1
    assert read['visible_lines'] == seed['visible_lines'] == 1


def test_missing_anchor_and_fully_visible_anchor():
    source = {'entry.py': 'def prompt():\n    pass\ndef confirm():\n    pass\n'}
    rows = diagnose('prompt or confirm', source, {'reads': [fragment(1, 2, 'ok')], 'seeds': []}, 10, 'read-first', ('prompt', 'confirm'))
    anchors = {row['name']: row for row in rows['anchors']}
    assert anchors['prompt']['fully_visible']
    assert anchors['confirm']['pool_missing']


def test_packing_handles_overlap_duplicate_and_oversize():
    pool = {'reads': [fragment(1, 2, '1234'), fragment(2, 3, 'abcd')],
            'seeds': [fragment(1, 2, '1234'), fragment(4, 4, 'x' * 9)]}
    row = diagnose('prompt', {'entry.py': 'def prompt():\n    a()\n    b()\n    c()\n'}, pool, 8, 'read-first', ('prompt',))
    assert [item['decision'] for item in row['packing']] == ['selected', 'selected', 'duplicate', 'larger_than_limit']
    assert row['anchors'][0]['pool_lines'] == 4
    assert row['anchors'][0]['visible_lines'] == 3  # Overlap counted once.


def test_identifier_occurrences_exclude_comments_and_strings():
    rows = public_anchors('prompt_suffix', {'entry.py': '# prompt_suffix\nx = "prompt_suffix"\nx.prompt_suffix = 1\n'})
    assert len(rows) == 1 and rows[0]['start_line'] == 3
