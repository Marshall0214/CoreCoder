"""Same v2 public checks and source context, optional frozen public relation matrix."""

import argparse
import hashlib
import json
from pathlib import Path

from docs.experiments import repair_forwarding_worker_v1 as context
from docs.experiments import salt_relations_audit_v1 as relations
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.worker import TracedLLM

public = relations.public
repair = relations.repair
POLICIES = ('checks-only', 'checks-and-relations')


def run_candidate(llm, job, events, result=None):
    result = {} if result is None else result
    if job['policy'] not in POLICIES or job['task_id'] != relations.TASK:
        raise ValueError('Unknown salt relation experiment')
    workspace, harness = Path(job['workspace']), Path(job['harness'])
    if ((harness / 'test_admission.py').read_bytes() != relations.CHECK.read_bytes()
            or repair.audit.sha(relations.CHECK) != job['check_code_hash']):
        raise ValueError('V2 public check differs from frozen code')
    matrix = job['relations']
    if hashlib.sha256(json.dumps(matrix, sort_keys=True).encode()).hexdigest() != job['relations_hash']:
        raise ValueError('Frozen public relation matrix changed')
    checked = lambda label: public.check_public(workspace, harness, job['harness_hash'],
        events.path.parent / ('public-' + label), Path(job['test_python']), job['task_id'])
    original, _ = checked('original')
    first = context.request_patch(llm, workspace, job, job['evidence'], events, 'initial')
    result.update(status=first['status'], prompt_hash=first['prompt_hash'], initial=first,
                  public_checks={'original': original}, feedback_attempts=0, stages=[first])
    if first['status'] != 'completed':
        result['feedback_skipped'] = 'initial_patch_invalid'
        return result
    candidate, output = checked('candidate')
    result['public_checks']['candidate'] = candidate
    if not (public.valid_failure(original) and public.valid_failure(candidate)):
        result['feedback_skipped'] = 'no_valid_assertion_failure_pair'
    else:
        packed = context.forwarding_context(workspace, job['allowed_files'], job['evidence'], job['description'])
        result['feedback_evidence_metadata'] = packed['metadata']
        feedback = {'frozen_test_code': (harness / 'test_admission.py').read_text(encoding='utf-8'),
                    'output': output, 'source': 'hand-authored public development checks; no final grader output'}
        if job['policy'] == 'checks-and-relations':
            feedback['public_parameter_relations'] = matrix
        result['feedback_attempts'] = 1
        final = context.request_patch(llm, workspace, job, packed['evidence'], events, 'feedback', feedback)
        result['stages'].append(final)
        result['status'] = final['status']
        if final['status'] == 'completed':
            result['public_checks']['final'], _ = checked('final')
    result['edited_files'] = sorted({name for stage in result['stages'] for name in stage.get('edited_files', [])})
    return result


def worker(path):
    job = json.loads(path.read_text(encoding='utf-8'))
    events = Events(path.parent / 'trace.jsonl', path.parent.name)
    result, llm = {'status': 'agent_error'}, None
    try:
        current = repair.config()
        repair.check_identity(current)
        llm = BudgetLLM(TracedLLM(current.model, 'ollama', current.base_url, events=events,
            temperature=0, reasoning_effort='none', max_tokens=2048, timeout=60), current, events)
        result = run_candidate(llm, job, events, result)
        repair.check_identity(current)
    except BudgetExceeded as exc:
        result.update(status='budget_exceeded', error=str(exc))
    except Exception as exc:  # noqa: BLE001 - preserve experimental failures
        result.update(status='agent_error', error=f'{type(exc).__name__}: {exc}')
    finally:
        result['metrics'] = llm.metrics() if llm else None
        (path.parent / 'worker-result.json').write_text(json.dumps(events.clean(result), indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    worker(parser.parse_args().worker.resolve())
