"""Request-only compression must preserve current evidence and failure diagnosis."""
import hashlib
import json

import pytest

from repairflow.issue_agent import SYSTEM, request_messages


def payload():
    row = {'path': 'module.py', 'symbol': 'f', 'content_hash': 'version-one', 'start_line': 1, 'end_line': 2,
           'offset': 0, 'content': 'def f():\n    return "UNIQUE_SOURCE_MARKER"\n',
           'complete_symbol': True, 'next_offset': None, 'kind': 'function'}
    return {'description': 'Fix the target; preserve existing behavior.', 'allowed_files': ['module.py'],
            'public_test_code': 'trusted public checks', 'fragments': [row],
            'observations': [{'step': 1, 'action': 'read_symbol', 'arguments': {'path': 'module.py', 'symbol': 'f'},
                              'status': 'completed', 'result': dict(row)}],
            'must_read_before_edit': [], 'remaining_steps': 19, 'remaining_edit_attempts': 6}


def test_full_policy_keeps_the_original_request_contract():
    data = payload()
    assert request_messages(data) == [{'role': 'system', 'content': SYSTEM},
                                     {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}]


def test_compact_read_has_one_source_copy_without_mutating_canonical_history():
    data = payload()
    before = json.dumps(data)
    messages = request_messages(data, 'compact-v1')
    compact = json.loads(messages[1]['content'])
    assert messages[1]['content'].count('UNIQUE_SOURCE_MARKER') == 1
    assert compact['fragments'] == data['fragments']
    assert {k: v for k, v in compact.items() if k != 'observations'} == {k: v for k, v in data.items() if k != 'observations'}
    result = compact['observations'][0]['result']
    assert 'content' not in result and result['content_available']
    assert {k: v for k, v in result.items() if k != 'content_available'} == {
        k: v for k, v in data['observations'][0]['result'].items() if k != 'content'}
    assert json.dumps(data) == before


@pytest.mark.parametrize('change', [{}, {'content_hash': 'version-two'}, {'offset': 6000},
                                  {'path': 'other.py'}, {'content': 'different source'}, {'start_line': 10}])
def test_old_changed_or_evicted_reads_cannot_claim_current_source_is_present(change):
    data = payload()
    data['fragments'] = [dict(data['fragments'][0], **change)] if change else []
    compact = json.loads(request_messages(data, 'compact-v1')[1]['content'])
    result = compact['observations'][0]['result']
    assert result['content_available'] is False and result['content_hash'] == 'version-one'
    assert 'content' not in result
    assert compact['fragments'] == data['fragments']


def test_edit_summaries_preserve_recovery_errors_and_public_feedback():
    data = payload()
    old, new = 'unapplied old candidate body', 'unapplied new candidate body'
    error = {'code': 'anchor_not_found', 'file': 'module.py', 'matches': 0, 'retryable': True, 'next_action': 'read_symbol'}
    feedback = {'code': 'public_validation_failed', 'scope': 'public only',
                'observations': 'Preserve.test_normal: AssertionError: expected 31, got None'}
    data['observations'].extend([
        {'step': 2, 'action': 'apply_patch', 'arguments': {'edits': [{'file': 'module.py', 'old': old, 'new': new}]},
         'status': 'tool_error', 'error': error, 'edit_attempt': 1},
        {'step': 3, 'action': 'apply_patch', 'arguments': {'edits': [{'file': 'module.py', 'old': old, 'new': new}]},
         'status': 'completed', 'changed_files': ['module.py'], 'net_changed_files': ['module.py'],
         'public_check_feedback': feedback, 'edit_attempt': 2},
    ])
    data['must_read_before_edit'] = ['module.py']
    before = json.dumps(data)
    messages = request_messages(data, 'compact-v1')
    assert old not in messages[1]['content'] and new not in messages[1]['content']
    compact = json.loads(messages[1]['content'])
    assert compact['observations'][1]['error'] == error
    assert compact['observations'][2]['public_check_feedback'] == feedback
    assert compact['observations'][2]['changed_files'] == ['module.py']
    assert compact['must_read_before_edit'] == ['module.py']
    summary = compact['observations'][1]['arguments']['edits'][0]
    assert summary == {'file': 'module.py', 'old_chars': len(old), 'new_chars': len(new),
                       'old_sha256': hashlib.sha256(old.encode()).hexdigest(),
                       'new_sha256': hashlib.sha256(new.encode()).hexdigest()}
    assert json.dumps(data) == before


@pytest.mark.parametrize('arguments', [{'edits': None}, {'edits': 'wrong type'}, {'edits': [False, {}]}, {}])
def test_invalid_edit_arguments_do_not_break_following_request(arguments):
    data = payload()
    data['observations'] = [{'step': 1, 'action': 'apply_patch', 'arguments': arguments,
                             'status': 'tool_error', 'error': {'code': 'invalid_patch_schema'}}]
    compact = json.loads(request_messages(data, 'compact-v1')[1]['content'])
    assert compact['observations'][0]['error']['code'] == 'invalid_patch_schema'


def test_unknown_policy_is_rejected():
    with pytest.raises(ValueError, match='observation policy'):
        request_messages(payload(), 'unknown')
