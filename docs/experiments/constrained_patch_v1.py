"""Reject empty and no-op structured patches before atomic source publication."""
import hashlib
import json
import shutil

from docs.experiments import public_feedback_v2 as previous
from evals.symbol_context import apply_symbol_patch


def check_patch(content):
    parsed = json.loads(content)
    edits = parsed.get('edits') if isinstance(parsed, dict) else None
    if not isinstance(edits, list) or not edits:
        raise ValueError('Patch requires nonempty edits')
    for edit in edits:
        if (not isinstance(edit, dict) or set(edit) != {'file', 'old', 'new'}
                or not all(isinstance(value, str) for value in edit.values())
                or not edit['old'] or edit['old'] == edit['new']):
            raise ValueError('Patch edit must contain a nonempty anchor and actual change')


def request(llm, workspace, job, evidence, root, stage, feedback=None):
    """Same first prompt as class-scoped baseline; only feedback extends round two."""
    previous.repair.validate_evidence(workspace, job['allowed_files'], evidence)
    system = previous.repair.patcher.SYMBOL_SYSTEM + ' Return a nonempty edits array that changes source. Identical old/new text is invalid. Use only exact supplied anchors; do not modify tests or bypass verification.'
    payload = {'description': job['description'], 'allowed_files': job['allowed_files'], 'fragments': evidence}
    if feedback is not None:
        system += (' These public development checks are not the final grader. Repair only source, '
                   'preserve normal behavior, and check expectations against the description. '
                   'Fragments are the current candidate; use current hashes and symbols. '
                   'Return one complete structured patch, not explanations.')
        payload['public_check_feedback'] = feedback
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
    previous.write_json(root / (stage + '-messages.json'), messages)
    result = {'status': 'invalid_patch', 'prompt_hash': hashlib.sha256(
        json.dumps(messages, ensure_ascii=False).encode()).hexdigest()}
    stage_workspace = root / (stage + '-staging')
    try:
        response = llm.chat(messages, tools=[])
        (root / (stage + '-response.txt')).write_text(response.content, encoding='utf-8')
        if response.tool_calls:
            raise ValueError('Unexpected tool call')
        # Atomic at the workflow level: malformed corrections cannot damage the first patch.
        shutil.copytree(workspace, stage_workspace)
        normalized = previous.baseline.envelope.normalize(response.content)
        check_patch(normalized)
        edited = apply_symbol_patch(normalized, stage_workspace,
                                    job['allowed_files'], evidence)
        if not edited or all((stage_workspace / name).read_bytes() == (workspace / name).read_bytes() for name in edited):
            raise ValueError('Patch must change source')
        for name in edited:
            compile((stage_workspace / name).read_bytes(), name, 'exec')
        for name in edited:
            (workspace / name).write_bytes((stage_workspace / name).read_bytes())
        result.update(status='completed', edited_files=edited)
    except Exception as exc:  # noqa: BLE001 - retain failed provider, budget and patch attempts
        result.update(status=str(exc) if isinstance(exc, previous.baseline.InvalidCompletion)
                      else 'budget_exceeded' if isinstance(exc, previous.baseline.BudgetExceeded) else 'invalid_patch',
                      error=f'{type(exc).__name__}: {exc}')
    return result

