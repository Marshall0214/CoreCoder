"""Zero-model replay of final real patches through staged public semantic acceptance."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from docs.experiments import anchored_patch_comparison_v1 as preparation
from docs.experiments import repair_public_checks_v1 as public
from docs.experiments import salt_relations_audit_v1 as relations
from docs.experiments import semantic_patch_transaction_v1 as gate
from evals.symbol_context import apply_symbol_patch

ROOT=public.ROOT
HISTORY=ROOT/'.tmp/real-defects/repair-hypothesis-compare-v2'


def audit(output):
    output=output.resolve()
    cases,grades=preparation.prepare(output)
    prior=json.loads((HISTORY/'experiment.json').read_text(encoding='utf-8'))
    if not prior['complete'] or prior['protocol']['protocol']!='public-repair-hypotheses-v2' or len(prior['runs'])!=4:
        raise ValueError('Expected complete four-run corrected hypothesis experiment')
    public.repair.check_identity(public.repair.config())
    output.mkdir(parents=True,exist_ok=False)
    hashes={}
    def freeze(path):
        hashes[path.relative_to(ROOT).as_posix()]=public.repair.audit.sha(path)
    for path in [Path(__file__),Path(gate.__file__),Path(gate.structural.__file__),Path(gate.observer.__file__),
                 ROOT/'evals/symbol_context.py',ROOT/'evals/patch.py',ROOT/'evals/process.py',HISTORY/'experiment.json']:
        if path.exists(): freeze(path)
    record={'protocol':'semantic-patch-audit-v1','complete':False,'model_calls':0,'private_grader_calls':0,
            'engine_hash':public.repair.audit.ENGINE,'historical':[],'positive':[],
            'source_hashes':{c['task_id']:c['before_hash'] for c in cases},'adapter_hashes':hashes}
    def save():
        (output/'audit.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    save()
    by_task={c['task_id']:(c,g) for c,g in zip(cases,grades)}
    checks={}
    for task in {r['task_id'] for r in prior['runs']}:
        canonical=relations.CHECK if task==relations.TASK else public.CHECK_ROOT/public.CHECKS[task]
        freeze(canonical)
        harness=output/'harnesses'/task; harness.mkdir(parents=True)
        (harness/'test_admission.py').write_bytes(canonical.read_bytes())
        checks[task]=gate.PublicCheck(harness,canonical,public.repair.audit.sha(canonical),
                                      public.repair.digest(public.repair.snapshot(harness)),task)
    for index,row in enumerate(prior['runs']):
        task,policy=row['task_id'],row['policy']; case,grade=by_task[task]
        branch=HISTORY/task/policy; root=output/f'historical-{index}'; workspace=root/'workspace'
        shutil.copytree(case['before'],workspace)
        job=json.loads((branch/'job.json').read_text(encoding='utf-8'))
        initial_path=branch/'initial-context.json'
        initial=json.loads(initial_path.read_text(encoding='utf-8'))['evidence'] if initial_path.exists() else job['evidence']
        apply_symbol_patch((branch/'response.txt').read_text(encoding='utf-8'),workspace,case['allowed_files'],initial)
        evidence=json.loads((branch/'feedback-context.json').read_text(encoding='utf-8'))['evidence']
        patch_path=branch/('feedback-patch.json' if policy=='public-hypotheses' else 'feedback-response.txt')
        for path in [branch/'job.json',branch/'response.txt',branch/'feedback-context.json',patch_path,branch/'worker-result.json']:
            freeze(path)
        if initial_path.exists(): freeze(initial_path)
        before=gate.structural.files(workspace)
        checked=gate.transact(patch_path.read_text(encoding='utf-8'),workspace,case['allowed_files'],evidence,
                              root/'transaction',grade['python'],job['imports'],checks[task])
        expected=row['accepted']
        valid=checked['accepted']==expected and (checked['committed'] if expected else gate.structural.files(workspace)==before)
        record['historical'].append({'task_id':task,'policy':policy,'historical_passed':expected,
                                     'matched_expected':valid,'transaction':checked})
        save()
    for task,(case,grade) in by_task.items():
        if task not in checks: continue
        root=output/'positive'/task; workspace=root/'workspace'; witness=root/'witness'
        shutil.copytree(case['before'],workspace); shutil.copytree(case['before'],witness)
        public.apply_witness(case,witness)
        old,new=gate.structural.files(workspace),gate.structural.files(witness)
        names=[name for name in old if old[name]!=new[name]]
        evidence=[{'path':name,'content':old[name].decode(),'content_hash':hashlib.sha256(old[name]).hexdigest()} for name in names]
        patch=json.dumps({'edits':[{'file':name,'old':old[name].decode(),'new':new[name].decode()} for name in names]})
        package='itsdangerous' if task.startswith('itsdangerous-') else 'click'
        imports=[{'module':package,'root':'src','path':f'src/{package}/__init__.py'}]
        checked=gate.transact(patch,workspace,case['allowed_files'],evidence,root/'transaction',grade['python'],imports,checks[task])
        record['positive'].append({'task_id':task,'matched_expected':checked['accepted'] and gate.structural.files(workspace)==new,
                                   'transaction':checked,'evidence_scope':'full changed files for offline human positive only'})
        save()
    record['complete']=(all(r['matched_expected'] for r in record['historical']+record['positive'])
                        and all(public.repair.audit.sha(ROOT/name)==value for name,value in hashes.items())
                        and all(public.repair.digest(public.repair.snapshot(c['before']))==c['before_hash'] for c in cases))
    record['summary']={'historical_wrong_rejected':sum(not r['historical_passed'] and not r['transaction']['accepted'] for r in record['historical']),
                       'historical_correct_committed':sum(r['historical_passed'] and r['transaction']['accepted'] for r in record['historical']),
                       'human_correct_committed':sum(r['matched_expected'] for r in record['positive'])}
    save()
    if not record['complete']: raise ValueError('Semantic gate offline replay failed')
    public.repair.check_identity(public.repair.config())
    print(json.dumps(dict(record['summary'],complete=True,model_calls=0,private_grader_calls=0)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--output',type=Path,required=True)
    audit(parser.parse_args().output)
