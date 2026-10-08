"""Balanced public diagnostics and minimal correction patches; frozen worker unchanged."""
import difflib
import json
import re
from pathlib import Path
from unittest.mock import patch

from docs.experiments import frozen_feedback_v1 as guarded

previous = guarded.previous
PATCH_GUIDANCE = (
    'Return the existing edits JSON schema, with the smallest unique old/new snippets needed. '
    'Do not copy whole functions or their unchanged docstrings when a local replacement suffices. '
    'The completion limit is 2048 tokens: old and new text both consume it. '
    'Use exact current fragments and enough surrounding text for uniqueness; do not use line-number edits. '
    'Before choosing edits, reconcile the defect description, failed assertions and already passing checks. '
    'Check every affected branch, ordering rule and cleanup path. Preserve cleanup even when returning early, '
    'and check that loops do not emit the same result twice. These are review questions, not diagnosed causes. '
    'Do not repeat an ineffective edit solely because its function executed. Return only the complete patch, '
    'without explanations or test modifications.'
)


def failures(text):
    """Keep every bounded failure's test name and assertion, not just the last traceback."""
    blocks = re.split(r'(?m)^(?=(?:FAIL|ERROR): )', text)[1:]
    result = []
    for block in blocks[:4]:
        lines = block.splitlines()
        # A separator immediately after the title precedes the traceback.
        body = lines[1:]
        if body and body[0].startswith('----------------------------------------------------------------------'):
            body = body[1:]
        body = '\n'.join(body).split('\n----------------------------------------------------------------------')[0]
        result.append({'test': lines[0][:160], 'detail': body[-320:]})
    if not result:
        result.append({'test': 'execution diagnostic', 'detail': text[-480:]})
    return result


def feedback(outcomes, workspace, job, root):
    groups = []
    diagnostics = []
    seen = {}
    for label, name in (('public', 'harness'), ('frozen', 'frozen_harness')):
        for group in ('Reproduce', 'Preserve'):
            outcome = outcomes[label][group]
            row = {'suite': label, 'group': group, 'passed': bool(outcome['passed']),
                   'tests_run': outcome.get('tests_run', 0), 'failures': outcome.get('failures', 0),
                   'errors': outcome.get('errors', 0)}
            if not outcome['passed']:
                path = root / ('initial-' + label) / (group + '.stderr.txt')
                text = path.read_text(encoding='utf-8', errors='replace')
                text = text.replace(str(workspace), '<candidate>').replace(str(job[name]), '<public-checks>')
                entries = failures(text)
                key = json.dumps(entries, sort_keys=True)
                if key not in seen:
                    seen[key] = len(diagnostics)
                    diagnostics.append(entries)
                row['diagnostic_index'] = seen[key]
            groups.append(row)
    first = json.loads(previous.baseline.envelope.normalize((root / 'initial-response.txt').read_text(encoding='utf-8')))
    changes = []
    remaining = 1600
    for edit in first.get('edits', []):
        diff = '\n'.join(difflib.unified_diff(edit['old'].splitlines(), edit['new'].splitlines(),
                                            n=1, lineterm=''))
        excerpt = diff[:remaining]
        if excerpt:
            changes.append({'file': edit['file'], 'diff': excerpt, 'truncated': len(diff) > len(excerpt)})
            remaining -= len(excerpt)
    return {'provenance': 'certified public outcomes and first candidate only; no independent grader/reference',
            'test_code': (Path(job['harness']) / 'test_admission.py').read_text(encoding='utf-8'),
            'groups': groups, 'diagnostics': diagnostics, 'initial_changes': changes,
            'repair_review': PATCH_GUIDANCE,
            'limits': 'At most 4 failure details/group; 320 chars/detail; 1600 chars of initial diff; excerpts may be partial'}


def run_candidate(llm, job, events):
    # A scoped worker-local replacement: seed selection, first request, validators,
    # completion budget and rollback retain their frozen implementations.
    with patch.object(guarded, 'feedback', feedback):
        result = guarded.run_candidate(llm, job, events)
    result['protocol'] = 'diagnostic-feedback-v1'
    return result
