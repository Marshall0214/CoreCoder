"""Recover edit failures and iterate public validation within a shared call/token budget."""
import shutil
from pathlib import Path

from docs.experiments import frozen_feedback_v1 as guarded
from docs.experiments import model_source_selection_v1 as selection
from evals.runner import digest, snapshot

previous = guarded.previous
RETRYABLE = {'invalid_patch', 'output_truncated', 'empty_final_answer'}


def guards_intact(job):
    for name in ('harness', 'frozen_harness'):
        if digest(snapshot(Path(job[name]))) != job[name + '_hash']:
            raise ValueError('Certified public harness changed')


def public_feedback(checks, workspace, job, root, stage):
    observations = [label + ':\n' + previous.diagnostic(checks[label], root / (stage + '-' + label),
                     workspace, Path(job[name])) for label, name in [('public', 'harness'), ('frozen', 'frozen_harness')]]
    return {'provenance': 'current certified public checks; no private grading',
            'test_code': (Path(job['harness']) / 'test_admission.py').read_text(encoding='utf-8'),
            'observations': '\n'.join(observations)[:4400]}


def run_candidate(llm, job, events):
    max_calls = job['max_calls']
    if type(max_calls) is not int or not 1 <= max_calls <= 6:
        raise ValueError('Require an explicit 1..6 call limit')
    root, workspace = events.path.parent, Path(job['workspace'])
    guarded.validate(job, root)
    original = root / 'original-workspace'
    shutil.copytree(workspace, original)
    result = {'status': 'agent_error', 'published': False, 'protocol': 'selected-source-repair-v1',
              'attempts': [], 'max_calls': max_calls, 'feedback_attempts': 0}
    evidence, observation = job['evidence'], None
    try:
        if job['policy'] == 'model-selected':
            evidence = selection.select(llm, job, events)
            result['selected_evidence'] = [{k: r[k] for k in ('path', 'symbol', 'start_line', 'end_line')} for r in evidence]
        seed_evidence = evidence
        for number in range(1, max_calls + 1):
            guards_intact(job)
            stage = 'initial' if number == 1 else f'round-{number:02d}'
            before = root / (stage + '-before')
            shutil.copytree(workspace, before)
            response = previous.request(llm, workspace, job, evidence, root, stage, observation)
            attempt = {'number': number, 'response': response,
                       'source_hash': digest(snapshot(workspace)), 'metrics': dict(llm.metrics())}
            result['attempts'].append(attempt)
            result['status'] = response['status']
            if number == 1:
                result['initial'] = response
                result['initial_metrics'] = dict(llm.metrics())
            if response['status'] != 'completed':
                guarded.restore(workspace, before, root)
                if response['status'] not in RETRYABLE:
                    break
                observation = {'provenance': 'actual edit application failure; no private grading',
                               'observations': response.get('error', response['status'])[:1200],
                               'repair_instruction': 'No edits from this attempt were retained. Return a complete JSON patch '
                               'using exact unique original snippets from the current fragments. Keep replacements minimal.'}
            else:
                checks = guarded.checked(workspace, job, root, stage)
                attempt['checks'] = checks
                result['final_checks'] = checks
                guards_intact(job)
                if guarded.valid(checks):
                    result.update(status='completed', published=True, correction_retained=number > 1)
                    break
                result['status'] = 'failed_public_validation'
                if not guarded.executable(checks):
                    result['stop_reason'] = 'public_execution_failure'
                    break
                observation = public_feedback(checks, workspace, job, root, stage)
                attempt['validated_source_hash'] = digest(snapshot(workspace))
            if number < max_calls:
                evidence = selection.refresh(workspace, job['allowed_files'], seed_evidence) if job['policy'] == 'model-selected' else previous.refresh_seeds(workspace, job['allowed_files'], seed_evidence)['evidence']
                result['feedback_attempts'] += 1
                events.emit('bounded_repair_retry', next_attempt=number + 1, reason=result['status'])
        if not result['published'] and 'stop_reason' not in result:
            result['stop_reason'] = 'call_limit' if len(result['attempts']) == max_calls else result['status']
    except Exception as exc:  # noqa: BLE001 - never publish after failed validation or infrastructure checks
        result.update(status='agent_error', error_type=type(exc).__name__, published=False)
    finally:
        if not result['published']:
            guarded.restore(workspace, original, root)
        result.update(metrics=llm.metrics(), final_source_hash=digest(snapshot(workspace)))
        result['original_restored'] = result['final_source_hash'] == job['original_hash']
    return result
