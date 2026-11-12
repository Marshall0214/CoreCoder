"""Deterministic request views; source receipts and public feedback stay whole."""
import copy
import hashlib
import json
from collections import Counter

from evals.context_policy import request_breakdown

POLICY = 'whole-receipt-context-v1'
ESTIMATE_METHOD = ('request_breakdown character heuristic, not a native tokenizer; '
                   'message text uses CJK/code/prose estimates and JSON schemas use characters / 3')
RECEIPT_FIELDS = ('receipt_id', 'path', 'content_hash', 'workspace_revision', 'kind', 'symbol',
                  'offset', 'next_offset', 'start_line', 'end_line', 'complete_symbol', 'complete_file')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def receipt_metadata(fragment):
    """Metadata is a location for re-reading, never permission or retained source."""
    row = {key: copy.deepcopy(fragment[key]) for key in RECEIPT_FIELDS if key in fragment}
    row.setdefault('offset', 0)
    row.setdefault('receipt_id', 'fragment-' + hashlib.sha256(encoded(fragment).encode()).hexdigest())
    content = fragment.get('content', '')
    row['content_chars'] = len(content) if isinstance(content, str) else 0
    if isinstance(content, str):
        row['fragment_sha256'] = hashlib.sha256(content.encode('utf-8')).hexdigest()
    return row


def observation_view(value):
    """Retain outcome/search metadata without repeating read bodies or patch text."""
    if isinstance(value, list):
        return [observation_view(row) for row in value]
    if not isinstance(value, dict):
        return copy.deepcopy(value)
    result = {}
    for key, item in value.items():
        if key in {'content', 'arguments', 'usage', 'patch'}:
            if key == 'patch' and isinstance(item, str):
                result.update(patch_chars=len(item), patch_sha256=hashlib.sha256(item.encode('utf-8')).hexdigest())
            continue
        result[key] = observation_view(item)
    return result


def build_context(*, system, task, guidance, revision, readable, editable, remaining,
                  fragments, feedback, actions, schema, target_tokens=12000):
    """Prefer current evidence over old outcomes; a target never cuts protected data.

    The caller supplies already public-filtered feedback and current read receipts.
    This pure view cannot verify file freshness, provider capacity or server truncation.
    Explicitly versioned stale receipts are omitted, and unversioned receipts retain
    the caller's existing evidence status rather than gaining a freshness guarantee.
    """
    if type(target_tokens) is not int or target_tokens < 1:
        raise ValueError('Context target must be a positive integer')
    system, task, guidance, readable, editable, fragments, feedback, actions, schema = copy.deepcopy(
        (system, task, guidance, readable, editable, fragments, feedback, actions, schema))
    observations = [observation_view(row) for row in actions[-6:]]
    selected = list(range(len(fragments)))
    omitted, omitted_observations = {}, []
    for index, row in enumerate(actions[:-6]):
        omitted_observations.append({'index': index, 'request': row.get('request'),
                                     'action': row.get('action'), 'reason': 'outside_recent_six'})

    def payload():
        return {'task': task, 'guidance': guidance, 'workspace_revision': revision,
                'readable_files': readable, 'allowed_files': editable, 'remaining_requests': remaining,
                'current_fragments': [fragments[index] for index in selected],
                'public_feedback': feedback, 'observations': observations,
                'omitted_fragments': [omitted[index] for index in sorted(omitted)],
                'context_policy': {'name': POLICY, 'target_tokens': target_tokens,
                    'omitted_observations': len(omitted_observations),
                    'notice': 'Omitted receipts are metadata, not source evidence. Re-read current source as needed. '
                              'The local estimate target is not a provider capacity guarantee.'}}

    def messages():
        return [{'role': 'system', 'content': system},
                {'role': 'user', 'content': json.dumps(payload(), ensure_ascii=False)}]

    def estimate():
        return request_breakdown(messages(), [], response_format=schema)

    before = estimate()
    identities = {}
    for index in reversed(selected):
        fragment = fragments[index]
        if 'workspace_revision' in fragment and fragment['workspace_revision'] != revision:
            omitted[index] = {**receipt_metadata(fragment), 'reason': 'stale_workspace_revision'}
            continue
        identity = encoded(fragment)
        if identity in identities:
            omitted[index] = {**receipt_metadata(fragment), 'reason': 'exact_duplicate',
                              'retained_receipt_id': receipt_metadata(fragments[identities[identity]])['receipt_id']}
        else:
            identities[identity] = index
    selected = [index for index in selected if index not in omitted]
    newest = selected[-1] if selected else None
    # Each optional item is removed whole. Even huge logs and source pages stay
    # byte-for-byte intact when selected; no mid-line or silent prefix truncation.
    while observations and estimate()['request_estimate'] > target_tokens:
        index = len(actions) - len(observations)
        row = actions[index]
        omitted_observations.append({'index': index, 'request': row.get('request'),
                                     'action': row.get('action'), 'reason': 'context_target'})
        observations.pop(0)
    while len(selected) > 1 and estimate()['request_estimate'] > target_tokens:
        index = selected.pop(0)
        omitted[index] = {**receipt_metadata(fragments[index]), 'reason': 'context_target'}
    result = messages()
    after = request_breakdown(result, [], response_format=schema)
    selected_receipts = [receipt_metadata(fragments[index]) for index in selected]
    input_chars = sum(len(row.get('content', '')) for row in fragments)
    selected_chars = sum(len(fragments[index].get('content', '')) for index in selected)
    manifest = {'policy': POLICY, 'target_tokens': target_tokens,
                'status': 'within_target' if after['request_estimate'] <= target_tokens else 'protected_over_target',
                'estimate_method': ESTIMATE_METHOD, 'server_truncation': 'not_verified',
                'estimate_before': before, 'estimate_after': after,
                'response_schema_estimate': after.get('response_format_estimate', 0),
                'estimate_before_scope': 'Full supplied fragments and last six metadata-only observations, before selection',
                'selected_receipts': selected_receipts,
                'selected_receipt_ids': [row['receipt_id'] for row in selected_receipts],
                'protected_receipt_id': receipt_metadata(fragments[newest])['receipt_id'] if newest is not None else None,
                'omitted_fragments': [omitted[index] for index in sorted(omitted)],
                'source_fragments': {'input_count': len(fragments), 'selected_count': len(selected),
                    'omitted_count': len(omitted), 'input_chars': input_chars,
                    'selected_chars': selected_chars, 'omitted_chars': input_chars - selected_chars},
                'observations': {'input_count': len(actions), 'selected_count': len(observations),
                    'omitted_count': len(omitted_observations),
                    'omitted_reason_counts': dict(Counter(row['reason'] for row in omitted_observations)),
                    'omitted': omitted_observations}}
    return result, manifest
