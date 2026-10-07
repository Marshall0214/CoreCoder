"""One fixed function-BM25 repair baseline across all 30 admitted tasks."""
import argparse
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

from docs.experiments import expanded_admission_v1 as admission
from docs.experiments import function_index_audit_v1 as functions
from docs.experiments import function_replace_v2 as envelope
from docs.experiments import repair_public_checks_v1 as public
from docs.experiments.provider_compare_worker_v1 import CheckedBudgetLLM, InvalidCompletion, Provider
from evals.process import run_process
from evals.runner import changes, digest, snapshot
from evals.runtime import BudgetExceeded, Events
from evals.symbol_context import apply_symbol_patch

ROOT = admission.ROOT
repair = public.repair


def worker(path):
    job=json.loads(path.read_text(encoding='utf-8'))
    root=path.parent; events=Events(root/'trace.jsonl','expanded-baseline')
    result={'status':'agent_error'};provider=llm=None
    try:
        repair.check_identity(repair.config())
        workspace=Path(job['workspace'])
        repair.validate_evidence(workspace,job['allowed_files'],job['evidence'])
        messages=[{'role':'system','content':repair.patcher.SYMBOL_SYSTEM},
                  {'role':'user','content':json.dumps({'description':job['description'],
                    'allowed_files':job['allowed_files'],'fragments':job['evidence']},ensure_ascii=False)}]
        result['prompt_hash']=hashlib.sha256(json.dumps(messages,ensure_ascii=False).encode()).hexdigest()
        (root/'messages.json').write_text(json.dumps(messages,ensure_ascii=False,indent=2),encoding='utf-8')
        provider=Provider('qwen',events);llm=CheckedBudgetLLM(provider,repair.config(),events)
        response=llm.chat(messages,tools=[])
        if response.tool_calls:raise ValueError('Unexpected tool call')
        (root/'response.txt').write_text(events.clean(response.content),encoding='utf-8')
        try:
            edited=apply_symbol_patch(envelope.normalize(response.content),workspace,job['allowed_files'],job['evidence'])
            for name in edited:compile((workspace/name).read_bytes(),name,'exec')
            result.update(status='completed',edited_files=edited)
        except (ValueError,TypeError,KeyError,SyntaxError) as exc:
            result.update(status='invalid_patch',error=str(exc))
        repair.check_identity(repair.config())
    except InvalidCompletion as exc:result.update(status=str(exc))
    except BudgetExceeded as exc:result.update(status='budget_exceeded',error=str(exc))
    except Exception as exc:  # noqa: BLE001 - retain every failed model branch
        result.update(status='agent_error',error=f'{type(exc).__name__}: {exc}')
    finally:
        result['metrics']=llm.metrics() if llm else None
        result['provider_calls']=provider.calls if provider else []
        (root/'worker-result.json').write_text(json.dumps(events.clean(result),indent=2),encoding='utf-8')
        if provider:provider.client.close()


def verify(case,workspace,root):
    before=snapshot(Path(case['before']));candidate=snapshot(workspace)
    changed,patch=changes(before,candidate)
    (root/'patch.diff').write_text(patch,encoding='utf-8')
    violations=sorted(set(changed)-set(case['allowed_files']))
    violations += [p for p in case['allowed_files'] if p not in candidate or (workspace/p).is_symlink()]
    if violations:return {'passed':False,'scope_violations':violations,'changed_files':changed,'groups':None}
    grading=root/'grading';shutil.copytree(case['before'],grading)
    for name in changed:(grading/name).write_bytes(candidate[name])
    outcomes=admission.groups(grading,Path(case['checks']),case['package'],case['source_root'],root/'grading-logs')
    return {'passed':all(g['passed'] for g in outcomes.values()),'scope_violations':[],
            'changed_files':changed,'groups':outcomes,'scope':'hand-authored Target and Controls; not entire upstream suite'}


def summarize(rows):
    def aggregate(items):
        return {'tasks':len(items),'passed':sum(r['accepted'] for r in items),
                'statuses':dict(Counter(r['status'] for r in items)),
                'target_passed':sum(bool((r['verification'].get('groups') or {}).get('Target',{}).get('passed')) for r in items),
                'controls_passed':sum(bool((r['verification'].get('groups') or {}).get('Controls',{}).get('passed')) for r in items),
                'model_calls':sum((r['worker'].get('metrics') or {}).get('llm_calls',0) for r in items),
                'tokens':sum((r['worker'].get('metrics') or {}).get('budget_accounted_tokens',0) for r in items),
                'missing_usage_calls':sum((r['worker'].get('metrics') or {}).get('missing_usage_calls',0) for r in items),
                'worker_seconds':round(sum(r['process']['seconds'] for r in items),4)}
    return {'overall':aggregate(rows),'split':{key:aggregate([r for r in rows if r['split']==key]) for key in sorted({r['split'] for r in rows})},
            'repository':{key:aggregate([r for r in rows if r['repo']==key]) for key in sorted({r['repo'] for r in rows})}}


def run(admitted_path,output):
    data=json.loads(admitted_path.read_text());output=output.resolve()
    if not data['complete'] or len(data['cases'])!=30 or len({c['task_id'] for c in data['cases']})!=30:
        raise ValueError('Require all 30 admitted unique tasks')
    if output.exists():raise ValueError('Use fresh output')
    if any(output.is_relative_to(Path(c[p]).resolve()) for c in data['cases'] for p in ('before','after','checks')):
        raise ValueError('Output overlaps frozen input')
    cases=data['cases'];repair.check_identity(repair.config())
    output.mkdir(parents=True)
    inputs={name:admission.history.sha(Path(name)) for name in [str(admitted_path.resolve()),str(Path(__file__).resolve()),
            str(Path(functions.__file__).resolve()),str(Path(envelope.__file__).resolve()),str(Path(admission.__file__).resolve())]}
    observations=[]
    # Freeze ALL retrieval and settings before any model calls; after/tests do not enter retrieval.
    for case in cases:
        index=functions.FunctionIndex(Path(case['before']),case['allowed_files']);index.refresh()
        packed=functions.pack(index,index.rank(case['description']+' contract contracts'))
        observations.append(dict(task_id=case['task_id'],**packed))
    observation_path=output/'observations.json';observation_path.write_text(json.dumps(observations,indent=2),encoding='utf-8')
    inputs[str(observation_path)]=admission.history.sha(observation_path)
    protocol={'name':'expanded-fixed-function-baseline-v1','expected_tasks':30,'unique_repositories':5,
              'config':repair.config().to_dict(),'engine_hash':repair.audit.ENGINE,'model_digest':repair.MODEL_DIGEST,
              'max_model_calls_per_task':1,'tools':[],'query':'description + contract contracts',
              'evidence':'complete function BM25; 6000 characters, 5 seeds, depth 0; no feedback',
              'split':'13 historical development + 7 new development + 10 new heldout; frozen before inference',
              'heldout_limits':'constructor reviewed fixes to author tests; unseen by strategy tuning, not guaranteed absent from pretraining',
              'prior_runs_included':False,'adapter_hashes':inputs,'no_private_grader_input':True,
              'comparison_limits':'new common one-shot protocol; not comparable to earlier task-specific two-call success rates'}
    report={'protocol':protocol,'complete':False,'runs':[]}
    def frozen():
        repair.check_identity(repair.config())
        if any(admission.history.sha(Path(p))!=value for p,value in inputs.items()):raise ValueError('Frozen adapters changed')
        for case in cases:
            for key,expected in [('before','before_hash'),('after','after_hash'),('checks','checks_hash')]:
                if digest(snapshot(Path(case[key])))!=case[expected]:raise ValueError('Frozen source/tests changed')
    def save():
        report['summary']=summarize(report['runs'])
        (output/'experiment.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    frozen();save()
    for case,observed in zip(cases,observations):
        frozen();root=output/case['task_id'];root.mkdir()
        workspace=root/'workspace';shutil.copytree(case['before'],workspace)
        job={'workspace':str(workspace),'description':case['description'],'allowed_files':case['allowed_files'],
             'evidence':observed['evidence']}
        path=root/'job.json';path.write_text(json.dumps(job,ensure_ascii=False),encoding='utf-8')
        process=run_process([sys.executable,'-B','-m','docs.experiments.expanded_baseline_v1','--worker',str(path)],
                            workspace,600,root/'worker.stdout.txt',root/'worker.stderr.txt',
                            dict(os.environ,PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8'))
        result_path=root/'worker-result.json'
        result=json.loads(result_path.read_text()) if result_path.exists() and process['returncode']==0 and not process['timed_out'] else {'status':'timeout' if process['timed_out'] else 'agent_error','metrics':None}
        verified=verify(case,workspace,root)
        accepted=result['status']=='completed' and verified['passed']
        report['runs'].append({'task_id':case['task_id'],'repo':case['repo'],'split':case['split'],
                               'previously_inspected':case['previously_inspected'],'worker':result,'verification':verified,
                               'accepted':accepted,'status':'passed' if accepted else 'failed_verification' if result['status']=='completed' else result['status'],
                               'process':process,'evidence_metadata':observed['metadata']})
        save();print(f"{case['task_id']}: {report['runs'][-1]['status']}",flush=True)
    frozen();report['complete']=len(report['runs'])==30;save()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',type=Path)
    parser.add_argument('--admission',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.worker:worker(args.worker.resolve())
    elif args.admission and args.output:run(args.admission.resolve(),args.output)
    else:parser.error('Provide --worker or --admission and --output')
