"""Optional actual patch history in bounded second-round repair context."""

import argparse
import hashlib
import json
from pathlib import Path

from docs.experiments import edited_context_v1 as retention
from docs.experiments import patch_delta_context_v1 as delta
from docs.experiments import patch_transaction_v1 as guard
from docs.experiments import repair_forwarding_worker_v1 as context
from docs.experiments import repair_public_checks_v1 as public
from docs.experiments import runtime_observation_v1 as observer
from docs.experiments import salt_relations_audit_v1 as relations
from docs.experiments import source_contract_context_v1 as contracts
from docs.experiments.provider_compare_worker_v1 import CheckedBudgetLLM, InvalidCompletion, Provider
from evals.runtime import BudgetExceeded, Events

repair = public.repair
POLICIES = ('public-feedback', 'unified-feedback')
RECOVERABLE = {'invalid_patch', 'invalid_python', 'added_duplicate_definitions', 'import_failed'}


def canonical_check(task_id):
    if task_id == relations.TASK:
        return relations.CHECK
    return public.CHECK_ROOT / public.CHECKS[task_id] if task_id in public.CHECKS else None


def pack_feedback(workspace, job):
    if job['task_id'] == relations.TASK:
        return context.forwarding_context(workspace, job['allowed_files'], job['evidence'], job['description'])
    return context.refresh_seeds(workspace, job['allowed_files'], job['evidence'])


def request_guarded(llm, workspace, job, evidence, events, stage, feedback=None, kind=None):
    """Keep initial and public-assertion prompts identical to the frozen adapter."""
    packed = None
    if job.get('context_policy') == 'source-contract' and job['task_id'] == relations.TASK:
        packed = contracts.pack(workspace, dict(job, evidence=evidence))
        evidence = packed['evidence']
    if stage == 'feedback' and job.get('retention_policy') == 'edited-first':
        packed = retention.pack(workspace, job['allowed_files'],
                                packed or {'evidence': evidence, 'metadata': {}},
                                job.get('retained_symbols', []))
        evidence = packed['evidence']
    if stage == 'feedback' and job.get('history_policy') == 'patch-delta':
        packed = delta.pack(workspace, job['allowed_files'], packed or {'evidence': evidence, 'metadata': {}},
                            job.get('retained_symbols', []), job['_task_start'])
        evidence = packed['evidence']
    repair.validate_evidence(workspace, job['allowed_files'], evidence)
    data = {'description': job['description'], 'allowed_files': job['allowed_files'],
            'fragments': [{key: row.get(key) for key in ('path', 'start_line', 'end_line', 'content_hash', 'content', 'symbol')}
                          for row in evidence]}
    if packed is not None:
        if 'source_contract_facts' in packed:
            data['source_contract_facts'] = packed['source_contract_facts']
        (events.path.parent / (stage + '-context.json')).write_text(json.dumps(packed, indent=2), encoding='utf-8')
    if packed and 'patch_history' in packed:
        data['patch_history'] = packed['patch_history']
    system = repair.patcher.SYMBOL_SYSTEM
    if kind == 'public':
        data['public_check_feedback'] = feedback
        system += (' These are frozen provisional public checks, not the final grader. '
                   'Check their expectations against the public description and repair source only. '
                   'Do not modify tests. Source fragments reflect the current candidate version.')
    elif kind == 'transaction':
        data['transaction_feedback'] = feedback
        system += ' The rejected patch was not committed. Repair only the displayed unchanged source, without adding duplicate definitions.'
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': json.dumps(data, ensure_ascii=False)}]
    result = {'stage': stage, 'prompt_hash': hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest(),
              'status': 'invalid_patch', 'evidence_chars': sum(len(row['content']) for row in evidence)}
    (events.path.parent / (stage + '-messages.json')).write_text(json.dumps(events.clean(messages), indent=2), encoding='utf-8')
    if packed is not None:
        result['context_metadata'] = packed['metadata']
    response = llm.chat(messages, tools=[])
    (events.path.parent / ('response.txt' if stage == 'initial' else 'feedback-response.txt')).write_text(
        events.clean(response.content), encoding='utf-8')
    if response.tool_calls:
        result['error'] = 'Unexpected tools outside the structured patch protocol'
        result['status'] = 'unexpected_tools'
        return result
    checked = guard.transact(response.content, workspace, job['allowed_files'], evidence,
                             events.path.parent / ('transaction-' + stage), job['test_python'], job['imports'])
    result.update(transaction=checked, status='completed' if checked['accepted'] else checked['reason'],
                  edited_files=checked['changed_files'] if checked['accepted'] else [])
    result['edited_symbols'] = retention.edited_symbols(response.content, evidence, checked)
    return result


def transaction_feedback(stage, events):
    checked = stage['transaction']
    # Short structural/load diagnostics; no private scorer or public harness logs.
    result = {'message': 'Patch rejected without changing source. Generate one corrected patch.', 'reason': checked['reason']}
    if checked.get('duplicates'):
        result['duplicates'] = [{key: row[key] for key in ('file', 'name', 'role', 'before', 'after')}
                                for row in checked['duplicates'][:5]]
    if checked.get('error'):
        result['error'] = checked['error'][:1000]
    if checked.get('import'):
        root = events.path.parent / 'transaction-initial'
        text = (root / 'import.stderr.txt').read_text(encoding='utf-8', errors='replace')[-1000:]
        result['import_error'] = text.replace(str(root), '<TRANSACTION>')
    return events.clean(result)


def run_candidate(llm, job, events, result=None):
    result = {} if result is None else result
    if job['policy'] not in POLICIES:
        raise ValueError('Unknown unified feedback policy')
    workspace = Path(job['workspace'])
    job = dict(job, _task_start=guard.files(workspace))
    canonical = canonical_check(job['task_id'])
    if canonical is not None:
        harness = Path(job['harness'])
        if ((harness / 'test_admission.py').read_bytes() != canonical.read_bytes()
                or repair.audit.sha(canonical) != job['check_code_hash']):
            raise ValueError('Public check differs from frozen code')
        def checked(label):
            return observer.check_public(workspace, harness, job['harness_hash'],
                                       events.path.parent / ('public-' + label), Path(job['test_python']), job['task_id'])
        original, _ = checked('original')
    else:
        checked, original = None, None
    unified = job['policy'] == 'unified-feedback'
    first = (request_guarded(llm, workspace, job, job['evidence'], events, 'initial') if unified
             else context.request_patch(llm, workspace, job, job['evidence'], events, 'initial'))
    result.update(status=first['status'], prompt_hash=first['prompt_hash'], stages=[first],
                  feedback_attempts=0, feedback_kind=None, public_checks={'original': original})
    feedback, kind = None, None
    if first['status'] != 'completed':
        transaction = first.get('transaction', {})
        if (unified and first['status'] in RECOVERABLE and transaction.get('original_unchanged')
                and not (transaction.get('import') or {}).get('timed_out')):
            feedback, kind = transaction_feedback(first, events), 'transaction'
        else:
            result['feedback_skipped'] = 'invalid_or_nonrecoverable_initial_patch'
    elif checked is not None:
        candidate, output = checked('candidate')
        result['public_checks']['candidate'] = candidate
        eligible = (public.valid_failure(candidate) if job['feedback_policy'] == 'assertion-only'
                    else observer.recoverable(candidate))
        result['observation_decision'] = {'classification': candidate['classification'], 'eligible': eligible}
        if public.valid_failure(original) and eligible:
            feedback = {'frozen_test_code': canonical.read_text(encoding='utf-8'), 'output': output,
                        'source': 'hand-authored public development checks; no final grader output'}
            if candidate['classification'] == 'candidate_runtime_error':
                feedback['runtime_observation'] = {'classification': candidate['classification'],
                    'issues': candidate['observation']['issues'][:5],
                    'source': 'public tests on candidate copy; no private grader'}
            kind = 'public'
        else:
            result['feedback_skipped'] = 'no_valid_assertion_failure_pair'
    else:
        result['feedback_skipped'] = 'no_certified_public_checks'
    if feedback is not None:
        job = dict(job, retained_symbols=first.get('edited_symbols', []))
        packed = pack_feedback(workspace, job)
        result.update(feedback_attempts=1, feedback_kind=kind, feedback_evidence_metadata=packed['metadata'])
        final = (request_guarded(llm, workspace, job, packed['evidence'], events, 'feedback', feedback, kind) if unified
                 else context.request_patch(llm, workspace, job, packed['evidence'], events, 'feedback', feedback))
        result['stages'].append(final)
        result['status'] = final['status']
        if final['status'] == 'completed' and checked is not None:
            result['public_checks']['final'], _ = checked('final')
    result['edited_files'] = sorted({name for stage in result['stages'] for name in stage.get('edited_files', [])})
    return result


def worker(path):
    job = json.loads(path.read_text(encoding='utf-8'))
    events = Events(path.parent / 'trace.jsonl', path.parent.name)
    result, llm, provider = {'status': 'agent_error'}, None, None
    try:
        config = repair.config()
        repair.check_identity(config)
        if job.get('history_policy') not in ('baseline', 'patch-delta'):
            raise ValueError('Unknown patch history policy')
        if job.get('retention_policy') not in ('baseline', 'edited-first'):
            raise ValueError('Unknown retention policy')
        if job.get('feedback_policy') not in ('assertion-only', 'runtime-feedback') or job.get('context_policy') != 'source-contract':
            raise ValueError('Unknown context policy')
        provider = Provider('qwen', events)
        llm = CheckedBudgetLLM(provider, config, events)
        run_candidate(llm, job, events, result)
        repair.check_identity(config)
    except retention.ContextUnavailable as exc:
        result.update(status='context_unavailable', error=str(exc))
    except InvalidCompletion as exc:
        result.update(status=str(exc))
    except BudgetExceeded as exc:
        result.update(status='budget_exceeded', error=str(exc))
    except Exception as exc:  # noqa: BLE001 - preserve failed live branches
        result.update(status='agent_error', error=f'{type(exc).__name__}: {exc}')
    finally:
        result['metrics'] = llm.metrics() if llm else None
        result['provider_calls'] = provider.calls if provider else []
        if provider and provider.calls and not result.get('prompt_hash'):
            result['prompt_hash'] = provider.calls[0]['prompt_hash']
        (path.parent / 'worker-result.json').write_text(json.dumps(events.clean(result), indent=2), encoding='utf-8')
        if provider:
            provider.client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    worker(parser.parse_args().worker.resolve())
