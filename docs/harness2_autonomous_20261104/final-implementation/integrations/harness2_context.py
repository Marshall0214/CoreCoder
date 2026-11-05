"""Declarative organization of already-visible receipts; no reads, tools or execution."""
import copy
import json

POLICY_FILE = 'context_policy.json'
DEFAULT = {'version': 1, 'deduplicate_reads': False, 'complete_symbols_first': False, 'read_index': False}


def policy(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate context policy field')
            result[key] = value
        return result

    value = json.loads(text, object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != set(DEFAULT) or type(value['version']) is not int
            or value['version'] != 1 or any(type(value[key]) is not bool for key in DEFAULT if key != 'version')):
        raise ValueError('Context policy requires version=1 and three booleans; no budgets, retrieval or code')
    return value


def organize(messages, config):
    """Retain task/constraints and every distinct receipt; only redundant reads may collapse."""
    policy(json.dumps(config))
    if config == DEFAULT:
        return messages  # Exact compatibility, including original JSON whitespace/order.
    result = copy.deepcopy(messages)
    payload = json.loads(result[-1]['content'])
    if payload.get('stage') not in ('exploration', 'candidate'):
        raise ValueError('Only checkpoint task payloads may use context policy')
    fragments = payload['current_fragments']
    observations = payload['observations']
    if config['deduplicate_reads']:
        seen, kept = set(), []
        for row in reversed(fragments):
            key = json.dumps(row, sort_keys=True)
            if key not in seen:
                kept.append(row)
                seen.add(key)
        fragments = list(reversed(kept))
        seen, kept = set(), []
        for row in reversed(observations):
            # Never remove failures, patches, search results or guard-stop observations.
            collapsible = row.get('action') in ('read_file', 'read_symbol') and row.get('status') == 'completed'
            key = json.dumps({k: v for k, v in row.items() if k != 'step'}, sort_keys=True)
            if not collapsible or key not in seen:
                kept.append(row)
            if collapsible:
                seen.add(key)
        observations = list(reversed(kept))
    if config['complete_symbols_first']:
        fragments = sorted(fragments, key=lambda row: not bool(row.get('complete_symbol')))
    payload['current_fragments'], payload['observations'] = fragments, observations
    if config['read_index']:
        payload['visible_read_index'] = [{key: row.get(key) for key in
            ('path', 'content_hash', 'kind', 'symbol', 'offset', 'complete_symbol')} for row in fragments]
    result[-1]['content'] = json.dumps(payload)
    return result
