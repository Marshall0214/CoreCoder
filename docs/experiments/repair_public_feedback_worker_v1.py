"""Shared first patch and at most one frozen-public-check feedback call."""

import argparse
import hashlib
import json
from pathlib import Path

from docs.experiments import repair_public_checks_v1 as public
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.symbol_context import apply_symbol_patch
from evals.worker import TracedLLM

repair = public.repair


def refresh_seeds(workspace, allowed, seeds):
    index = public.comparison.directed.retrieval.FunctionIndex(workspace, allowed)
    index.refresh()
    ranked = []
    for seed in seeds:
        found = [chunk for chunk in index.chunks if chunk.path == seed['path']
                 and index.names[(chunk.path, chunk.start_line, chunk.end_line)] == seed['symbol']]
        if len(found) == 1:
            ranked.append((seed.get('score', 0), found[0]))
    packed = public.comparison.directed.retrieval.pack(index, ranked)
    repair.validate_evidence(workspace, allowed, packed['evidence'])
    return packed


def request_patch(llm, workspace, job, evidence, events, stage, feedback=None):
    repair.validate_evidence(workspace, job['allowed_files'], evidence)
    fragments = [{k: r.get(k) for k in ('path', 'start_line', 'end_line', 'content_hash', 'content', 'symbol')}
                 for r in evidence]
    data = {'description': job['description'], 'allowed_files': job['allowed_files'], 'fragments': fragments}
    system = repair.patcher.SYMBOL_SYSTEM
    if feedback is not None:
        data['public_check_feedback'] = feedback
        system += (' These are frozen provisional public checks, not the final grader. '
                   'Check their expectations against the public description and repair source only. '
                   'Do not modify tests. Source fragments reflect the current candidate version.')
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}]
    result = {'stage': stage, 'prompt_hash': hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest(),
              'evidence_chars': sum(len(r['content']) for r in evidence), 'status': 'invalid_patch'}
    events.emit('public_patch_requested', **result)
    response = llm.chat(messages, tools=[])
    (events.path.parent / ('response.txt' if stage == 'initial' else 'feedback-response.txt')).write_text(
        events.clean(response.content), encoding='utf-8')
    try:
        if response.tool_calls:
            raise ValueError('Tools are outside the structured patch protocol')
        result.update(edited_files=apply_symbol_patch(response.content, workspace, job['allowed_files'], evidence),
                      status='completed')
    except (ValueError, TypeError, KeyError, OSError) as exc:
        result.update(error=f'{type(exc).__name__}: {exc}')
    return result


def run_candidate(llm, job, events, result=None):
    result = {} if result is None else result
    if job['policy'] not in {'single', 'public-feedback'} or job['task_id'] not in public.TARGETS:
        raise ValueError('Unknown public feedback protocol')
    workspace, harness = Path(job['workspace']), Path(job['harness'])
    canonical = public.CHECK_ROOT / public.CHECKS[job['task_id']]
    if ((harness / 'test_admission.py').read_bytes() != canonical.read_bytes()
            or repair.audit.sha(canonical) != job['check_code_hash']):
        raise ValueError('Public check differs from frozen developer code')
    checked = lambda label: public.check_public(workspace, harness, job['harness_hash'],
                       events.path.parent / ('public-' + label), Path(job['test_python']), job['task_id'])
    original, _ = checked('original')
    first = request_patch(llm, workspace, job, job['evidence'], events, 'initial')
    result.update(status=first['status'], prompt_hash=first['prompt_hash'], initial=first,
                  public_checks={'original': original}, feedback_attempts=0, stages=[first])
    if first['status'] != 'completed':
        result['feedback_skipped'] = 'initial_patch_invalid'
        return result
    candidate, output = checked('candidate')
    result['public_checks']['candidate'] = candidate
    if job['policy'] == 'single':
        result['feedback_skipped'] = 'single_call_control'
    elif not (public.valid_failure(original) and public.valid_failure(candidate)):
        result['feedback_skipped'] = 'no_valid_assertion_failure_pair'
    else:
        packed = refresh_seeds(workspace, job['allowed_files'], job['evidence'])
        result['feedback_evidence_metadata'] = packed['metadata']
        feedback = {'frozen_test_code': (harness / 'test_admission.py').read_text(encoding='utf-8'),
                    'output': output, 'source': 'hand-authored public development checks; no final grader output'}
        result['feedback_attempts'] = 1
        final = request_patch(llm, workspace, job, packed['evidence'], events, 'feedback', feedback)
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
    except Exception as exc:  # noqa: BLE001 - preserve failed experimental branches
        result.update(status='agent_error', error=f'{type(exc).__name__}: {exc}')
    finally:
        result['metrics'] = llm.metrics() if llm else None
        (path.parent / 'worker-result.json').write_text(json.dumps(events.clean(result), indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    worker(parser.parse_args().worker.resolve())
