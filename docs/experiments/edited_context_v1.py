"""Retain committed edit anchors as complete current-version functions."""
import json

from docs.experiments import function_index_audit_v1 as functions
from docs.experiments import source_contract_context_v1 as contracts


class ContextUnavailable(ValueError):
    """Mandatory current edit anchors cannot be supplied under fixed limits."""


def edited_symbols(response, evidence, transaction):
    if not transaction['accepted']:
        return []
    selected = []
    for edit in json.loads(response)['edits']:
        if edit['old'] == edit['new'] or edit['file'] not in transaction['changed_files']:
            continue
        rows = [r for r in evidence if r['path'] == edit['file'] and edit['old'] in r['content']]
        rows.sort(key=lambda r: r['end_line'] - r['start_line'])
        if not rows or not rows[0].get('symbol'):
            raise ContextUnavailable('Committed edit has no displayed function anchor')
        minimum = rows[0]['end_line'] - rows[0]['start_line']
        keys = {(r['path'], r['symbol']) for r in rows
                if r['end_line'] - r['start_line'] == minimum}
        if len(keys) != 1:
            raise ContextUnavailable('Committed edit has ambiguous function anchors')
        key = {'path': rows[0]['path'], 'symbol': rows[0]['symbol']}
        if key not in selected:
            selected.append(key)
    return selected


def pack(workspace, allowed, base, mandatory, limit=6000, top_k=5):
    index = functions.FunctionIndex(workspace, allowed)
    index.refresh()
    facts = base.get('source_contract_facts', '')
    used = len(contracts.encoded(facts)) if 'source_contract_facts' in base else 0
    selected, discarded = [], []
    required = list(dict.fromkeys((r['path'], r['symbol']) for r in mandatory))
    if len(required) > top_k:
        raise ContextUnavailable('Too many mandatory edited functions')
    for path, symbol in required:
        info = index.parsed.get(path)
        chunks = [c for c in index.chunks if c.path == path
                  and index.names[(path, c.start_line, c.end_line)] == symbol]
        if info is None or len(chunks) != 1:
            raise ContextUnavailable(f'Edited function missing or ambiguous: {path}:{symbol}')
        chunk = chunks[0]
        row = {'path': path, 'symbol': symbol, 'start_line': chunk.start_line, 'end_line': chunk.end_line,
               'content': chunk.content, 'content_hash': info['hash'], 'complete_symbol': True,
               'reason': 'committed_edit', 'rank': len(selected) + 1, 'score': 0}
        if any(r['path'] == path and r['start_line'] <= row['end_line']
               and r['end_line'] >= row['start_line'] for r in selected):
            raise ContextUnavailable('Overlapping mandatory edited functions')
        if used + len(row['content']) > limit:
            raise ContextUnavailable('Edited functions exceed fixed context budget')
        selected.append(row)
        used += len(row['content'])
    for row in base['evidence']:
        overlap = any(r['path'] == row['path'] and r['start_line'] <= row['end_line']
                      and r['end_line'] >= row['start_line'] for r in selected)
        reason = ('overlap' if overlap else 'seed_limit' if len(selected) >= top_k
                  else 'budget' if used + len(row['content']) > limit else None)
        if reason:
            discarded.append({'path': row['path'], 'symbol': row.get('symbol'), 'reason': reason})
        else:
            selected.append(row)
            used += len(row['content'])
    contracts.unified.repair.validate_evidence(workspace, allowed, selected)
    result = dict(base, evidence=selected)
    result['metadata'] = dict(base.get('metadata', {}), strategy='edited-functions-first',
                              retained_symbols=[list(k) for k in required], seed_count=len(selected),
                              evidence_chars=sum(len(r['content']) for r in selected),
                              combined_chars=used, max_chars=limit, discarded=discarded)
    return result
