"""One structured patch request using versioned, bounded symbol evidence."""

import hashlib
import json

from .fixed_evidence import SYSTEM
from .symbol_context import apply_symbol_patch, symbol_evidence

PROTOCOL = 'symbol-patch-development-v1'
SYMBOL_SYSTEM = SYSTEM + (
    ' Evidence contains exact source fragments, not necessarily complete files or symbols. '
    'Respect start_line, end_line, symbol_range and complete_symbol. '
    'Each old string must appear in a single supplied fragment and match uniquely in its full file. '
    'Do not edit omitted source, reconstruct whole files, or assume partial symbols are complete. '
    'If the evidence is insufficient, return {"edits": []}.'
)


def run_symbol_patch(llm, workspace, description, allowed_files, config, events):
    evidence = symbol_evidence(workspace, description, allowed_files, events,
                               max_chars=config.search_max_chars, top_k=config.evidence_top_k,
                               depth=config.evidence_dependency_depth, index_mode='symbols',
                               query_policy='identifiers', packing_policy='dependency-reserve',
                               dependency_scope='full-seed')
    manifest = [{key: value for key, value in row.items() if key != 'content'} for row in evidence]
    result = {'protocol': PROTOCOL, 'evidence_manifest': manifest,
              'evidence_chars': sum(len(row['content']) for row in evidence),
              'selection': {'index_mode': 'symbols', 'query_policy': 'identifiers',
                            'packing_policy': 'dependency-reserve', 'dependency_scope': 'full-seed'}}
    if not evidence:
        events.emit('symbol_patch_skipped', reason='no_evidence')
        return {**result, 'status': 'no_evidence', 'edited_files': []}
    payload = json.dumps({'description': description, 'allowed_files': list(allowed_files),
                          'fragments': evidence}, ensure_ascii=False)
    messages = [{'role': 'system', 'content': SYMBOL_SYSTEM}, {'role': 'user', 'content': payload}]
    result['prompt_hash'] = hashlib.sha256((SYMBOL_SYSTEM + '\n' + payload).encode()).hexdigest()
    result['protocol_prompt_hash'] = result['prompt_hash']
    result['tool_schema_hash'] = hashlib.sha256(b'[]').hexdigest()
    events.emit('symbol_patch_request', protocol=PROTOCOL, files=manifest, chars=result['evidence_chars'])
    response = llm.chat(messages, tools=[])
    (events.path.parent / 'symbol-patch-response.txt').write_text(events.clean(response.content), encoding='utf-8')
    result['final_message'] = response.content
    try:
        if response.tool_calls:
            raise ValueError('Tool calls are not supported by the symbol patch protocol')
        changed = apply_symbol_patch(response.content, workspace, allowed_files, evidence)
        result.update(status='completed', edited_files=changed)
        events.emit('symbol_patch_applied', files=changed)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        result.update(status='invalid_patch', error=f'{type(exc).__name__}: {exc}')
        events.emit('symbol_patch_rejected', error=result['error'])
    return result
