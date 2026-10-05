"""One structured patch request using versioned, bounded symbol evidence."""

import hashlib
import json
import re

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
BEHAVIOR_CHECK = (
    ' Before returning edits, check the proposed behavior against every public requirement. '
    'Cover positive, negative and boundary cases explicitly stated in the description, including '
    'whitespace, exact matching and preserved behavior when mentioned. '
    'Distinguish activation decisions from ordinary value conversion when the requirement makes that distinction; '
    'a converted value being nonempty does not itself prove the activation condition is satisfied. '
    'Inspect all supplied fragments that implement those behaviors rather than fixing only the first match. '
    'Return the same edits-only JSON schema; do not output explanations or a checklist.'
)


def public_requirements(description):
    """Verbatim sentence spans only; no task-specific examples, labels or inferred answers."""
    rows = []
    for match in re.finditer(r'[^.!?\n]+(?:[.!?]+|(?=\n|$))', description):
        raw = match.group()
        text = raw.strip()
        if text:
            start = match.start() + len(raw) - len(raw.lstrip())
            rows.append({'text': text, 'span': [start, start + len(text)]})
    return rows


def run_symbol_patch(llm, workspace, description, allowed_files, config, events, prompt_policy='baseline',
                     feedback=None, response_name='symbol-patch-response.txt'):
    if prompt_policy not in {'baseline', 'behavior-check'}:
        raise ValueError('Unknown symbol patch prompt policy')
    evidence = symbol_evidence(workspace, description, allowed_files, events,
                               max_chars=config.search_max_chars, top_k=config.evidence_top_k,
                               depth=config.evidence_dependency_depth, index_mode='symbols',
                               query_policy='identifiers', packing_policy='dependency-reserve',
                               dependency_scope='full-seed')
    manifest = [{key: value for key, value in row.items() if key != 'content'} for row in evidence]
    result = {'protocol': PROTOCOL, 'prompt_policy': prompt_policy, 'evidence_manifest': manifest,
              'evidence_hash': hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
              'evidence_chars': sum(len(row['content']) for row in evidence),
              'selection': {'index_mode': 'symbols', 'query_policy': 'identifiers',
                            'packing_policy': 'dependency-reserve', 'dependency_scope': 'full-seed'}}
    if not evidence:
        events.emit('symbol_patch_skipped', reason='no_evidence')
        return {**result, 'status': 'no_evidence', 'edited_files': []}
    data = {'description': description, 'allowed_files': list(allowed_files), 'fragments': evidence}
    system = SYMBOL_SYSTEM
    if prompt_policy == 'behavior-check':
        data['public_requirements'] = public_requirements(description)
        system += BEHAVIOR_CHECK
        events.emit('symbol_public_requirements', requirements=data['public_requirements'],
                    source='public_description', semantic_coverage_verified=False)
    if feedback is not None:
        data['public_check_feedback'] = feedback
        system += (' These are frozen provisional public checks, not the final grader. '
                   'Check their expectations against the public description and repair source only. '
                   'Do not modify tests. Source fragments reflect the current candidate version.')
        result['protocol'] = 'symbol-feedback-development-v1'
    payload = json.dumps(data, ensure_ascii=False)
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': payload}]
    result['prompt_hash'] = hashlib.sha256((system + '\n' + payload).encode()).hexdigest()
    result['protocol_prompt_hash'] = result['prompt_hash']
    result['tool_schema_hash'] = hashlib.sha256(b'[]').hexdigest()
    events.emit('symbol_patch_request', protocol=PROTOCOL, prompt_policy=prompt_policy,
                files=manifest, chars=result['evidence_chars'])
    response = llm.chat(messages, tools=[])
    (events.path.parent / response_name).write_text(events.clean(response.content), encoding='utf-8')
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
