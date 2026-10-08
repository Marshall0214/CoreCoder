import pytest

from docs.experiments.source_fallthrough_context_v1 import enrich, facts


def test_records_if_call_and_following_cleanup_without_reference():
    result = facts('''def leave(self):
    if self.ready:
        self.close()
    pop_context()
''')
    assert result[0]['call'] == 'self.close()'
    assert result[0]['original_following_statements'] == ['pop_context()']


def test_records_reset_after_call_but_not_existing_terminal_returns():
    assert facts('def close(self):\n self.stack.close()\n self.stack = Stack()')[0]['original_following_statements'] == ['self.stack = Stack()']
    assert facts('def terminal(self):\n return self.close()') == []
    assert facts('def guarded(self):\n if self.ready:\n  return self.close()\n reset()') == []


def test_metadata_respects_combined_budget_and_does_not_alter_evidence():
    rows = [{'content': 'def leave():\n close()\n cleanup()', 'complete_symbol': True, 'content_hash': 'unchanged'}]
    enriched, chars = enrich(rows)
    assert chars > len(rows[0]['content'])
    assert 'original_execution_order' not in rows[0]
    assert enriched[0]['content_hash'] == rows[0]['content_hash']
    with pytest.raises(ValueError, match='budget'):
        enrich(rows, max_chars=len(rows[0]['content']))


def test_partial_symbols_are_not_interpreted_as_complete_functions():
    rows = [{'content': 'def leave():\n close()\n cleanup()', 'complete_symbol': False}]
    assert enrich(rows)[0] == rows
