"""Candidate checkpoints must use read evidence, not answers or hidden-test feedback."""
import json
from types import SimpleNamespace

import pytest

from evals.repository_checkpoint import LedgerTools, explore
from evals.runtime import Events


@pytest.fixture
def tools(tmp_path):
    source, output = tmp_path / 'workspace', tmp_path / 'output'
    source.mkdir()
    output.mkdir()
    (source / 'code.py').write_text('def f():\n    return 1\n\ndef g():\n    return 3\n', encoding='utf-8', newline='\n')
    return LedgerTools(source, output)


class Replies:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.messages = []

    def chat(self, messages, **kwargs):
        self.messages.append(messages)
        return SimpleNamespace(content=json.dumps(next(self.replies)), tool_calls=[])


def run(llm, tools):
    return explore(llm, tools, {'problem_statement': 'f must return 2'}, tools.output,
                   Events(tools.output / 'trace.jsonl', 'offline-checkpoint'))


def test_symbol_and_file_offsets_do_not_overwrite_each_other(tools):
    tools.dispatch('read_symbol', {'path': 'code.py', 'symbol': 'f', 'offset': 0}, 1)
    tools.dispatch('read_file', {'path': 'code.py', 'offset': 0}, 2)
    assert len(tools.evidence) == 2
    assert any(row.get('symbol') == 'f' and row['complete_symbol'] for row in tools.evidence)
    tools.dispatch('read_file', {'path': 'code.py', 'offset': 0}, 3)
    assert len(tools.evidence) == 2


def test_published_edit_invalidates_all_old_receipts_and_advances_revision(tools):
    tools.dispatch('read_file', {'path': 'code.py'}, 1)
    tools.dispatch('read_symbol', {'path': 'code.py', 'symbol': 'f'}, 2)
    tools.dispatch('apply_patch', {'edits': [{'file': 'code.py', 'old': 'return 1', 'new': 'return 2'}]}, 3)
    assert not tools.evidence and tools.revision == 1
    tools.dispatch('read_symbol', {'path': 'code.py', 'symbol': 'f'}, 4)
    assert 'return 2' in tools.evidence[0]['content']


def test_complete_read_moves_to_candidate_and_stops_after_valid_patch(tools):
    llm = Replies([{'action': 'read_symbol', 'arguments': {'path': 'code.py', 'symbol': 'f'}},
                   {'edits': [{'file': 'code.py', 'old': 'return 1', 'new': 'return 2'}]}])
    assert run(llm, tools) == 'candidate_generated'
    payload = json.loads(llm.messages[1][-1]['content'])
    assert payload['stage'] == 'candidate' and payload['current_fragments'][0]['complete_symbol']
    assert 'FAIL_TO_PASS' not in json.dumps(llm.messages)
    assert 'return 2' in (tools.workspace / 'code.py').read_text()
    assert len(llm.messages) == 2


def test_candidate_can_request_specific_dependency_and_then_edit(tools):
    llm = Replies([{'action': 'read_symbol', 'arguments': {'path': 'code.py', 'symbol': 'f'}},
                   {'need_context': {'path': 'code.py', 'symbol': 'g'}},
                   {'edits': [{'file': 'code.py', 'old': 'return 1', 'new': 'return g() - 1'}]}])
    assert run(llm, tools) == 'candidate_generated'
    fragments = json.loads(llm.messages[2][-1]['content'])['current_fragments']
    assert {row['symbol'] for row in fragments} == {'f', 'g'}


def test_unread_anchor_is_rejected_and_cannot_modify_source(tools):
    llm = Replies([{'action': 'read_symbol', 'arguments': {'path': 'code.py', 'symbol': 'f'}},
                   {'edits': [{'file': 'code.py', 'old': 'return 3', 'new': 'return 4'}]},
                   {'edits': [{'file': 'code.py', 'old': 'return 3', 'new': 'return 5'}]},
                   {'edits': [{'file': 'code.py', 'old': 'return 3', 'new': 'return 6'}]}])
    assert run(llm, tools) == 'consecutive_error_limit'
    assert 'return 3' in (tools.workspace / 'code.py').read_text()


def test_exploration_still_has_repeated_action_protection(tools):
    action = {'action': 'search', 'arguments': {'query': 'f'}}
    llm = Replies([action] * 4)
    assert run(llm, tools) == 'repeated_action_limit'
    rows = json.loads((tools.output / 'actions.json').read_text())
    assert rows[-1]['reason'] == 'repeated_action_limit'


def test_candidate_cannot_silently_return_to_repeated_file_prefix_reads(tools):
    llm = Replies([{'action': 'read_symbol', 'arguments': {'path': 'code.py', 'symbol': 'f'}},
                   *[{'action': 'read_file', 'arguments': {'path': 'code.py'}} for _ in range(3)]])
    assert run(llm, tools) == 'consecutive_error_limit'
    rows = json.loads((tools.output / 'actions.json').read_text())
    assert all(row['error']['code'] == 'invalid_candidate' for row in rows[1:])
