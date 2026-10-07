"""Actual first-patch history within the fixed evidence budget, never edit anchors."""
import difflib
import hashlib

from docs.experiments import edited_context_v1 as retention
from docs.experiments import patch_transaction_v1 as guard

HISTORY_LIMIT = 2000


def history(before, workspace, allowed):
    # Read bytes directly: experimental grading snapshots use a different text digest.
    current = guard.files(workspace)
    if set(before) != set(current):
        raise retention.ContextUnavailable('Patch history cannot represent created or deleted files')
    changed = sorted(name for name in before if before[name] != current[name])
    if set(changed) - set(allowed):
        raise retention.ContextUnavailable('Patch history includes out-of-scope changes')
    rows = []
    for name in changed:
        try:
            old, new = before[name].decode('utf-8'), current[name].decode('utf-8')
        except UnicodeDecodeError as exc:
            raise retention.ContextUnavailable('Patch history requires UTF-8 source') from exc
        rows.append({'path': name, 'before_sha256': hashlib.sha256(before[name]).hexdigest(),
                     'current_sha256': hashlib.sha256(current[name]).hexdigest(),
                     'diff': ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                                        fromfile=f'before/{name}', tofile=f'current/{name}', n=0))})
    return {'role': 'history_only; edits must anchor on current fragments', 'files': rows}


def pack(workspace, allowed, base, mandatory, before, limit=6000, top_k=5):
    delta = history(before, workspace, allowed)
    if not delta['files']:
        return base
    cost = len(retention.contracts.encoded(delta))
    if cost > HISTORY_LIMIT:
        raise retention.ContextUnavailable('Patch history exceeds fixed history budget')
    result = retention.pack(workspace, allowed, base, mandatory, limit=limit-cost, top_k=top_k)
    result['patch_history'] = delta
    result['metadata'] = dict(result['metadata'], strategy='current-functions-plus-actual-patch-history',
                              history_chars=cost, history_max_chars=HISTORY_LIMIT,
                              combined_chars=result['metadata']['combined_chars']+cost, max_chars=limit)
    return result
