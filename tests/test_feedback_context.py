"""Whole-receipt request compaction without models, files, or a Docker daemon."""
import copy
import hashlib
import json

import pytest

from evals.context_policy import request_breakdown
from repairflow.feedback_context import build_context


def fragment(name, content, *, receipt=None, revision=3, offset=0, complete=True):
    return {'path': name, 'content': content, 'content_hash': hashlib.sha256(content.encode()).hexdigest(),
            'receipt_id': receipt or name, 'workspace_revision': revision, 'offset': offset,
            'symbol': 'f', 'kind': 'function', 'complete_symbol': complete, 'complete_file': False,
            'next_offset': None if complete else offset + len(content)}


def inputs(**updates):
    values = {'system': 'Repair using current read receipts and public evidence.',
              'task': {'instance_id': 'example', 'problem_statement': 'Preserve callers and repair f.'},
              'guidance': 'Verify the result before finishing.', 'revision': 3,
              'readable': ['pkg/a.py', 'pkg/b.py'], 'editable': ['pkg/a.py'], 'remaining': 17,
              'fragments': [], 'feedback': {'status': 'rejected', 'public_checks': {'Reproduce': {'passed': False}}},
              'actions': [], 'schema': {'type': 'json_schema', 'json_schema': {'name': 'action', 'schema': {'type': 'object'}}},
              'target_tokens': 12000}
    values.update(updates)
    return values


def unpack(values):
    messages, manifest = build_context(**values)
    return messages, json.loads(messages[1]['content']), manifest


def test_large_history_compacts_before_old_source_and_preserves_latest_error_and_read():
    old = fragment('pkg/a.py', 'OLD_SOURCE\n' * 2500)
    latest = fragment('pkg/b.py', 'def f():\n    return FACTOR\n', complete=False)
    feedback = {'status': 'rejected', 'action_error': {'code': 'anchor_not_supplied', 'message': 'Read current f.'},
                'rollback': {'reason': 'new_preservation_regression', 'failed_validation': {'stderr': 'AssertionError\n' * 20}}}
    values = inputs(fragments=[old, latest], feedback=feedback, actions=[
        {'request': number, 'action': 'search', 'result': {'matches': [{'line': 'old outcome\n' * 500}]}}
        for number in range(1, 7)], target_tokens=1600)
    messages, payload, manifest = unpack(values)
    assert payload['public_feedback'] == feedback
    assert payload['current_fragments'] == [latest]
    assert payload['current_fragments'][0]['complete_symbol'] is False
    assert payload['observations'] == []
    assert manifest['estimate_after']['request_estimate'] < manifest['estimate_before']['request_estimate']
    assert manifest['observations']['omitted_reason_counts'] == {'context_target': 6}
    assert manifest['omitted_fragments'][0]['reason'] == 'context_target'
    assert old['content'] not in messages[1]['content']
    assert manifest['status'] == 'within_target'


def test_history_keeps_search_outcomes_but_never_old_arguments_source_diff_or_usage():
    actions = [{'request': number, 'action': 'read_symbol', 'arguments': {'path': 'pkg/a.py', 'symbol': 'SECRET_ARG'},
                'usage': {'prompt_tokens': 123}, 'result': {'path': 'pkg/a.py', 'content': 'OLD_READ_BODY'}}
               for number in range(10)]
    actions[-1] = {'request': 9, 'action': 'apply_patch', 'arguments': {'edits': [{'old': 'OLD_ANCHOR', 'new': 'NEW_BODY'}]},
                   'result': {'changed_files': ['pkg/a.py'], 'patch': 'RAW_PATCH_BODY'},
                   'error': {'code': 'retained_error'}}
    actions[-2] = {'request': 8, 'action': 'search', 'result': {'matches': [{'path': 'pkg/b.py', 'line': 'FACTOR = 2'}],
                                                          'truncated': False}}
    messages, payload, manifest = unpack(inputs(actions=actions))
    assert [row['request'] for row in payload['observations']] == [4, 5, 6, 7, 8, 9]
    assert payload['observations'][-2]['result']['matches'] == [{'path': 'pkg/b.py', 'line': 'FACTOR = 2'}]
    assert payload['observations'][-1]['error']['code'] == 'retained_error'
    assert payload['observations'][-1]['result']['patch_chars'] == len('RAW_PATCH_BODY')
    assert not any(value in messages[1]['content'] for value in
                   ('SECRET_ARG', 'OLD_READ_BODY', 'OLD_ANCHOR', 'NEW_BODY', 'RAW_PATCH_BODY', 'prompt_tokens'))
    assert manifest['observations']['omitted_reason_counts'] == {'outside_recent_six': 4}


def test_omission_receipts_are_explicit_and_inputs_are_unchanged():
    values = inputs(fragments=[fragment('pkg/a.py', 'earlier code\n' * 3000, offset=8),
                              fragment('pkg/b.py', 'def f():\n    return 2\n')], target_tokens=1400)
    original = copy.deepcopy(values)
    messages, payload, manifest = unpack(values)
    assert values == original
    assert manifest['omitted_fragments'] == payload['omitted_fragments']
    omission = payload['omitted_fragments'][0]
    assert {key: omission[key] for key in ('receipt_id', 'path', 'content_hash', 'offset', 'reason')} == {
        'receipt_id': 'pkg/a.py', 'path': 'pkg/a.py', 'content_hash': original['fragments'][0]['content_hash'],
        'offset': 8, 'reason': 'context_target'}
    assert 'content' not in omission and omission['content_chars'] == len(original['fragments'][0]['content'])
    assert manifest['selected_receipt_ids'] == ['pkg/b.py']
    assert manifest['selected_receipts'][0]['content_hash'] == original['fragments'][1]['content_hash']
    manifest['selected_receipts'][0]['path'] = 'changed'
    payload['public_feedback']['status'] = 'changed'
    assert values == original
    assert build_context(**values)[0] == messages


def test_exact_duplicate_retains_newest_and_chronological_order():
    a, b = fragment('pkg/a.py', 'a = 1\n'), fragment('pkg/b.py', 'b = 2\n')
    _, payload, manifest = unpack(inputs(fragments=[a, b, copy.deepcopy(a)]))
    assert payload['current_fragments'] == [b, a]
    assert manifest['selected_receipt_ids'] == ['pkg/b.py', 'pkg/a.py']
    assert manifest['omitted_fragments'][0]['reason'] == 'exact_duplicate'
    assert manifest['omitted_fragments'][0]['retained_receipt_id'] == 'pkg/a.py'
    assert manifest['source_fragments'] == {
        'input_count': 3, 'selected_count': 2, 'omitted_count': 1,
        'input_chars': 3 * len(a['content']), 'selected_chars': 2 * len(a['content']), 'omitted_chars': len(a['content'])}


def test_same_location_with_different_source_is_not_called_exact_duplicate():
    a = fragment('pkg/a.py', 'a = 1\n')
    changed = {**a, 'content': 'a = 2\n'}
    _, payload, manifest = unpack(inputs(fragments=[a, changed]))
    assert payload['current_fragments'] == [a, changed]
    assert manifest['omitted_fragments'] == []


def test_protected_payload_over_target_is_sent_intact_with_honest_estimate():
    receipt = fragment('pkg/a.py', 'def f():\n    return 2\n' * 300)
    feedback = {'action_error': {'code': 'invalid_patch', 'message': 'Error\n' * 1500}}
    values = inputs(fragments=[receipt], feedback=feedback, target_tokens=1)
    messages, payload, manifest = unpack(values)
    assert payload['task'] == values['task'] and payload['guidance'] == values['guidance']
    assert payload['readable_files'] == values['readable'] and payload['allowed_files'] == values['editable']
    assert payload['workspace_revision'] == 3 and payload['remaining_requests'] == 17
    assert payload['current_fragments'] == [receipt] and payload['public_feedback'] == feedback
    assert manifest['status'] == 'protected_over_target'
    assert manifest['estimate_after'] == request_breakdown(messages, [], response_format=values['schema'])
    assert manifest['estimate_after']['request_estimate'] > manifest['target_tokens']
    assert manifest['server_truncation'] == 'not_verified' and 'not a native tokenizer' in manifest['estimate_method']
    assert manifest['response_schema_estimate'] == len(json.dumps(values['schema'])) // 3


def test_unicode_source_counts_use_characters_and_hashes_use_utf8_bytes():
    text = 'def 名称():\n    return "中文🙂"\n'
    receipt = fragment('pkg/a.py', text, offset=7, complete=False)
    messages, payload, manifest = unpack(inputs(fragments=[receipt]))
    assert payload['current_fragments'] == [receipt]
    assert '中文🙂' in messages[1]['content']
    assert manifest['source_fragments']['selected_chars'] == len(text) < len(text.encode('utf-8'))
    assert manifest['selected_receipts'][0]['fragment_sha256'] == hashlib.sha256(text.encode()).hexdigest()
    assert manifest['selected_receipts'][0]['next_offset'] == 7 + len(text)


def test_explicit_stale_revision_is_omitted_before_selecting_protected_receipt():
    current = fragment('pkg/a.py', 'current = 1\n')
    stale = fragment('pkg/b.py', 'stale = 2\n', revision=2)
    _, payload, manifest = unpack(inputs(fragments=[current, stale]))
    assert payload['current_fragments'] == [current]
    assert manifest['protected_receipt_id'] == current['receipt_id']
    assert payload['omitted_fragments'][0]['reason'] == 'stale_workspace_revision'


@pytest.mark.parametrize('target', [0, -1, True, 1.5, '12000', None])
def test_context_target_requires_positive_integer(target):
    with pytest.raises(ValueError, match='positive integer'):
        build_context(**inputs(target_tokens=target))
