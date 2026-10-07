"""Task-owned tentative repair and bounded feedback, with final public-gated publication."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from docs.experiments import edited_context_worker_v1 as tentative
from docs.experiments import semantic_patch_transaction_v1 as gate
from docs.experiments.provider_compare_worker_v1 import CheckedBudgetLLM, InvalidCompletion, Provider
from evals.runtime import BudgetExceeded, Events

repair=tentative.repair


def run_candidate(llm,job,events,result=None):
    result={} if result is None else result
    workspace=Path(job['workspace']).resolve(); root=events.path.parent.resolve()
    if root.is_relative_to(workspace) or workspace.is_relative_to(root):
        raise ValueError('Task artifacts must be separate from the task workspace')
    before=gate.structural.files(workspace)
    result.update(status='agent_error',committed=False,edited_files=[],attempt={},lifecycle=[],
                  task_start_sha256=gate.digest(before),original_unchanged=True)
    def transition(state):
        result['lifecycle'].append(state)
        events.emit('repair_lifecycle',state=state)
    try:
        canonical=tentative.canonical_check(job['task_id'])
        if canonical is None:
            result['status']='no_certified_public_checks'
            transition('rejected')
            return result
        check=gate.PublicCheck(Path(job['harness']),canonical,job['check_code_hash'],job['harness_hash'],job['task_id'])
        gate.validate_check(check)
        if (job.get('policy')!='unified-feedback' or job.get('retention_policy')!='edited-first'
                or job.get('feedback_policy')!='runtime-feedback' or job.get('context_policy')!='source-contract'):
            raise ValueError('Expected frozen unified feedback and edited-function context policies')
        stage=root/'tentative-source'
        shutil.copytree(workspace,stage)
        transition('tentative')
        tentative.run_candidate(llm,dict(job,workspace=str(stage)),events,result['attempt'])
        attempt=result['attempt']
        result['prompt_hash']=attempt.get('prompt_hash')
        result['feedback_attempts']=attempt.get('feedback_attempts',0)
        result['tentative_edited_files']=attempt.get('edited_files',[])
        transition('feedback_finished')
        if attempt['status']!='completed':
            result['status']=attempt['status']; transition('rejected'); return result
        candidate=gate.structural.files(stage)
        names=sorted(set(candidate)^set(before))
        if names:
            result.update(status='candidate_scope_violation',scope_violations=names)
            transition('rejected'); return result
        changed=sorted(name for name in before if before[name]!=candidate[name])
        if any(name not in job['allowed_files'] for name in changed):
            result.update(status='candidate_scope_violation',scope_violations=[n for n in changed if n not in job['allowed_files']])
            transition('rejected'); return result
        if not changed:
            result['status']='no_changes'; transition('rejected'); return result
        if gate.structural.files(workspace)!=before:
            result['status']='source_changed'; transition('rejected'); return result
        # Trusted net diff rebases previously validated model edits onto the task-start bytes.
        # These full-file anchors are never supplied to the model as extra context.
        evidence=[{'path':name,'content':before[name].decode('utf-8'),
                   'content_hash':hashlib.sha256(before[name]).hexdigest()} for name in changed]
        patch=json.dumps({'edits':[{'file':name,'old':before[name].decode('utf-8'),
                                   'new':candidate[name].decode('utf-8')} for name in changed]})
        (root/'net-patch.json').write_text(events.clean(patch),encoding='utf-8')
        transition('validating')
        transaction=gate.transact(patch,workspace,job['allowed_files'],evidence,root/'publication',
                                  job['test_python'],job['imports'],check)
        result['publication']=transaction
        result.update(status='completed' if transaction['accepted'] else transaction['reason'],
                      committed=transaction['committed'],edited_files=transaction['changed_files'] if transaction['committed'] else [])
        transition('committed' if transaction['committed'] else 'rejected')
        return result
    except BudgetExceeded as exc:
        result.update(status='budget_exceeded',error=str(exc)); transition('rejected'); return result
    except InvalidCompletion as exc:
        result.update(status=str(exc)); transition('rejected'); return result
    except tentative.retention.ContextUnavailable as exc:
        result.update(status='context_unavailable',error=str(exc)); transition('rejected'); return result
    except Exception as exc:  # noqa: BLE001 - preserve tentative source and diagnostics on failure
        result.update(status='agent_error',error=f'{type(exc).__name__}: {exc}'); transition('rejected'); return result
    finally:
        result['original_unchanged']=gate.structural.files(workspace)==before
        result['task_end_sha256']=gate.digest(gate.structural.files(workspace))
        result['attempt_artifacts']='tentative-source; initial/feedback messages and public/transaction logs'
        (root/'lifecycle.json').write_text(json.dumps(events.clean(result),indent=2),encoding='utf-8')


def worker(path):
    job=json.loads(path.read_text(encoding='utf-8')); events=Events(path.parent/'trace.jsonl',path.parent.name)
    result,llm,provider={'status':'agent_error'},None,None
    try:
        config=repair.config(); repair.check_identity(config)
        provider=Provider('qwen',events); llm=CheckedBudgetLLM(provider,config,events)
        run_candidate(llm,job,events,result)
        repair.check_identity(config)
    except Exception as exc:  # noqa: BLE001 - record setup or identity failure without losing artifacts
        result.update(status='agent_error',error=f'{type(exc).__name__}: {exc}')
    finally:
        result.update(metrics=llm.metrics() if llm else None,provider_calls=provider.calls if provider else [])
        (path.parent/'worker-result.json').write_text(json.dumps(events.clean(result),indent=2),encoding='utf-8')
        if provider: provider.client.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--worker',type=Path,required=True)
    worker(parser.parse_args().worker.resolve())
