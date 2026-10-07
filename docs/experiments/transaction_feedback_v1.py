"""Opt-in transaction rejection feedback, at most two patch attempts."""

import hashlib
import json
from pathlib import Path

from docs.experiments import patch_transaction_v1 as guard
from evals.fixed_evidence import SYSTEM
from evals.runtime import BudgetExceeded

POLICIES = ('generic', 'diagnostic')
RECOVERABLE = {'invalid_patch', 'invalid_python', 'added_duplicate_definitions', 'import_failed',
               'empty_final_answer', 'output_truncated'}


def diagnostic(result, attempt, events):
    """Only validation diagnostics enter feedback; never behavior/grader output."""
    value = {key: result[key] for key in ('reason', 'duplicates', 'error') if key in result}
    if result.get('import') is not None:
        path = attempt / 'transaction/import.stderr.txt'
        value['import_stderr'] = path.read_text(encoding='utf-8', errors='replace')[-2000:]
    text = json.dumps(value, ensure_ascii=False).replace(str(attempt), '<attempt>')
    # JSON serialization escapes Windows backslashes.
    text = text.replace(json.dumps(str(attempt))[1:-1], '<attempt>')
    return events.clean(json.loads(text))


def run_candidate(llm, job, events, seed_patch=None):
    """Normal mode: <=2 LLM calls sharing the supplied BudgetLLM instance.

    Fault-recovery probe: a caller-supplied synthetic seed occupies attempt one,
    without a model call or token charge, followed by <=1 fresh LLM call.
    """
    if job['policy'] not in POLICIES:
        raise ValueError('Unknown transaction feedback policy')
    workspace = Path(job['workspace'])
    baseline = guard.files(workspace)
    result = {'status': 'transaction_rejected', 'transaction_accepted': False, 'attempts': [],
              'feedback_attempts': 0, 'seeded': seed_patch is not None}
    previous, rejected = None, None
    for number in (1, 2):
        attempt = events.path.parent / f'attempt-{number:02d}'
        attempt.mkdir(exist_ok=False)
        data = {key: job[key] for key in ('description', 'allowed_files', 'files')}
        if number == 2:
            if guard.files(workspace) != baseline:
                result['status'] = 'source_changed'
                break
            result['feedback_attempts'] = 1
            feedback = {'message': 'Previous patch was rejected and never committed. Generate one corrected patch against the displayed unchanged source.',
                        'rejected_patch': previous[:12000], 'rejected_patch_truncated': len(previous) > 12000}
            if job['policy'] == 'diagnostic':
                feedback['validation'] = diagnostic(rejected, events.path.parent / 'attempt-01', events)
            data['transaction_feedback'] = feedback
        messages = [{'role': 'system', 'content': SYSTEM},
                    {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}]
        row = {'attempt': number, 'origin': 'synthetic-seed' if number == 1 and seed_patch is not None else 'model',
               'prompt_sha256': hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()}
        (attempt / 'messages.json').write_text(json.dumps(events.clean(messages), indent=2), encoding='utf-8')
        content, reason = '', None
        if row['origin'] == 'synthetic-seed':
            content = seed_patch
        else:
            try:
                response = llm.chat(messages, tools=[])
                content = response.content
                if response.tool_calls:
                    reason = 'unexpected_tools'
                elif getattr(llm.inner, 'telemetry', {}).get('done_reason') == 'length':
                    reason = 'output_truncated'
                elif not content.strip():
                    reason = 'empty_final_answer'
            except BudgetExceeded as exc:
                row.update(status='budget_exceeded', error=str(exc))
                result['attempts'].append(row)
                result['status'] = 'budget_exceeded'
                break
            except Exception as exc:  # noqa: BLE001 - preserve provider failures without retry
                row.update(status='provider_error', error=f'{type(exc).__name__}: {exc}')
                result['attempts'].append(row)
                result['status'] = 'provider_error'
                break
        (attempt / 'response.txt').write_text(events.clean(content), encoding='utf-8')
        if reason is None:
            checked = guard.transact(content, workspace, job['allowed_files'], job['files'], attempt / 'transaction',
                                     job['test_python'], job['imports'])
        else:
            checked = {'accepted': False, 'committed': False, 'reason': reason,
                       'original_unchanged': guard.files(workspace) == baseline, 'import': None}
        row.update(status=checked['reason'], transaction=checked)
        result['attempts'].append(row)
        events.emit('transaction_attempt', **row)
        if checked['accepted']:
            result.update(status='transaction_accepted', transaction_accepted=True)
            break
        result['status'] = checked['reason']
        if (checked['reason'] not in RECOVERABLE or not checked['original_unchanged']
                or (checked.get('import') or {}).get('timed_out')):
            result['feedback_skipped'] = 'nonrecoverable_or_source_changed'
            break
        previous, rejected = content, checked
    result['metrics'] = llm.metrics()
    (events.path.parent / 'feedback-result.json').write_text(json.dumps(events.clean(result), indent=2), encoding='utf-8')
    return result
