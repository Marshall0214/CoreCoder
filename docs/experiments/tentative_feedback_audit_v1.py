"""Exact-prompt two-round answer replay for task-level tentative publication; no inference."""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

from corecoder.llm import LLMResponse
from docs.experiments import anchored_patch_comparison_v1 as preparation
from docs.experiments import tentative_feedback_worker_v1 as worker
from evals.runtime import BudgetLLM, Events

ROOT=worker.tentative.public.ROOT
HISTORY=ROOT/'.tmp/real-defects/edited-context-compare-v1'


def normalize_messages(messages):
    value=json.loads(json.dumps(messages))
    for row in value:
        if row['role']!='user': continue
        data=json.loads(row['content'])
        feedback=data.get('public_check_feedback',{})
        if 'output' in feedback:
            feedback['output']=re.sub(r'(?m)^Ran (\d+) (tests?) in \d+\.\d+s$', r'Ran \1 \2 in <TIME>s', feedback['output'])
        row['content']=json.dumps(data,ensure_ascii=False)
    return value


class Replay:
    model='qwen3.5:27b'
    def __init__(self,branch,historical):
        self.branch,self.historical,self.calls=branch,historical,[]
    def chat(self,messages,tools=None):
        index=len(self.calls)
        if index>=len(self.historical['stages']):
            raise ValueError('Unexpected extra replay request')
        actual=hashlib.sha256(json.dumps(messages,ensure_ascii=False).encode()).hexdigest()
        expected=self.historical['stages'][index]['prompt_hash']
        comparison='exact'
        if actual!=expected:
            frozen=json.loads((self.branch/('initial-messages.json' if index==0 else 'feedback-messages.json')).read_text(encoding='utf-8'))
            if normalize_messages(messages)!=normalize_messages(frozen):
                raise ValueError('Replay differs beyond the public unittest timing line')
            comparison='unittest_timing_normalized'
        if tools:
            raise ValueError('Unexpected replay tools')
        response=(self.branch/('response.txt' if index==0 else 'feedback-response.txt')).read_text(encoding='utf-8')
        usage=self.historical['provider_calls'][index]
        self.calls.append({'prompt_hash':actual,'historical_prompt_hash':expected,'comparison':comparison,'matched_historical':True})
        return LLMResponse(content=response,prompt_tokens=usage['prompt_tokens'],completion_tokens=usage['completion_tokens'])


def audit(output):
    output=output.resolve(); cases,grades=preparation.prepare(output)
    prior=json.loads((HISTORY/'experiment.json').read_text(encoding='utf-8'))
    if not prior['complete'] or prior['protocol']['protocol']!='edited-function-context-v1':
        raise ValueError('Expected frozen edited-context experiment')
    selected=[r for r in prior['runs'] if r['policy']=='edited-first' and r['task_id'] in worker.tentative.public.TARGETS]
    if len(selected)!=2:
        raise ValueError('Expected two public-feedback task replays')
    worker.repair.check_identity(worker.repair.config())
    output.mkdir(parents=True,exist_ok=False)
    hashes={}
    def freeze(path): hashes[path.relative_to(ROOT).as_posix()]=worker.repair.audit.sha(path)
    for path in [Path(__file__),Path(worker.__file__),Path(worker.gate.__file__),Path(worker.tentative.__file__),
                 Path(worker.tentative.retention.__file__),Path(worker.tentative.contracts.__file__),
                 Path(worker.tentative.guard.__file__),Path(worker.tentative.observer.__file__),HISTORY/'experiment.json']:
        freeze(path)
    by_task={c['task_id']:(c,g) for c,g in zip(cases,grades)}
    report={'protocol':'tentative-feedback-audit-v1','complete':False,'model_calls':0,'private_grader_calls':0,
            'engine_hash':worker.repair.audit.ENGINE,'adapter_hashes':hashes,'runs':[]}
    def save(): (output/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    save()
    for row in selected:
        task=row['task_id']; case,grade=by_task[task]; branch=HISTORY/task/'edited-first'
        root=output/task; workspace=root/'workspace'; shutil.copytree(case['before'],workspace)
        before=worker.gate.structural.files(workspace)
        job=json.loads((branch/'job.json').read_text(encoding='utf-8'))
        canonical=worker.tentative.canonical_check(task); freeze(canonical)
        harness=root/'harness'; harness.mkdir(); (harness/'test_admission.py').write_bytes(canonical.read_bytes())
        job.update(workspace=str(workspace.resolve()),harness=str(harness.resolve()),
                   harness_hash=worker.repair.digest(worker.repair.snapshot(harness)),
                   check_code_hash=worker.repair.audit.sha(canonical),test_python=str(grade['python']))
        for name in ('job.json','response.txt','feedback-response.txt','worker-result.json','initial-messages.json','feedback-messages.json'): freeze(branch/name)
        artifacts=root/'run'; artifacts.mkdir(); events=Events(artifacts/'trace.jsonl',task)
        raw=Replay(branch,row['worker']); llm=BudgetLLM(raw,worker.repair.config(),events)
        value=worker.run_candidate(llm,job,events)
        expected=row['accepted']
        matched=value['committed']==expected and (worker.gate.structural.files(workspace)==worker.gate.structural.files(branch/'workspace')
                  if expected else worker.gate.structural.files(workspace)==before)
        report['runs'].append({'task_id':task,'matched_expected':matched,'historical_passed':expected,
                               'replayed_requests':len(raw.calls),'matched_prompt_hashes':raw.calls,
                               'replayed_usage_not_new_inference':llm.metrics(),'worker':value})
        save()
    report['complete']=(all(r['matched_expected'] and r['replayed_requests']==2 for r in report['runs'])
                        and all(worker.repair.audit.sha(ROOT/name)==value for name,value in hashes.items()))
    report['summary']={'correct_published':sum(r['worker']['committed'] for r in report['runs']),
                       'wrong_task_start_preserved':sum(not r['worker']['committed'] and r['worker']['original_unchanged'] for r in report['runs']),
                       'matched_requests_except_unittest_timing':sum(r['replayed_requests'] for r in report['runs']),
                       'exact_prompt_matches':sum(c['comparison']=='exact' for r in report['runs'] for c in r['matched_prompt_hashes'])}
    save(); worker.repair.check_identity(worker.repair.config())
    if not report['complete']: raise ValueError('Tentative lifecycle replay failed')
    print(json.dumps(dict(report['summary'],complete=True,model_calls=0,private_grader_calls=0)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--output',type=Path,required=True)
    audit(parser.parse_args().output)
