"""Post-hoc diagnostic only: never alter Agent artifacts or feed graders to a model."""
import difflib
import hashlib
import json
import os
import shutil
from pathlib import Path

from repairflow.checks import groups
from sandbox import runner

root=Path('D:/project_other/CoreCoder')
trial=root/'.tmp/harness2-toolz-pilot-20261104-v2'
out=root/'.tmp/harness2-review-20261104'
out.mkdir(exist_ok=False)
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
case=read(trial/'identity/job.json')['case']
original=(trial/'input/toolz/itertoolz.py').read_text(encoding='utf-8')
candidate=(trial/'executions/issue-cc-agg1/toolz-join-unmatched/agg1/candidate-source/toolz/itertoolz.py').read_text(encoding='utf-8')
insert='''            # Yield unmatched left rows with right_default
            for key, matches in iteritems(d):
                if key not in seen_keys:
                    for match in matches:
                        yield (match, right_default)
'''
assert candidate.count(insert)==1
assert original.count('iteritems(d)')==1 and candidate.count('iteritems(d)')==2
assert candidate.replace(insert,'',1)==original
names_only=candidate.replace('iteritems(d)','d.items()')
names_and_duplicate=names_only.replace(insert.replace('iteritems(d)','d.items()'),'',1)
assert names_and_duplicate==original.replace('iteritems(d)','d.items()')
os.environ['CORECODER_TEST_BACKEND']='docker'
policy=runner.preflight()
expected=read(trial/'identity/identity.json')['sandbox']
assert policy==expected
runner.ACTIVE_POLICY.set(policy)
variants={
    'candidate_unchanged':candidate,
    'candidate_names_only':names_only,
    'candidate_names_and_duplicate':names_and_duplicate,
}
results={}
protected=[trial/'report.json',trial/'protocol.json',trial/'core-result.json',
           trial/'recovery.json',root/'docs/harness2-20261104.json',
           Path(case['checks'])/'test_admission.py']
before={str(p):sha(p) for p in protected}
for name,text in variants.items():
    folder=out/name
    source=folder/'source'
    shutil.copytree(trial/'input',source)
    (source/'toolz/itertoolz.py').write_text(text,encoding='utf-8',newline='\n')
    (folder/'diagnostic.diff').write_text(''.join(difflib.unified_diff(
        candidate.splitlines(keepends=True),text.splitlines(keepends=True),
        fromfile='agent-candidate',tofile=name)),encoding='utf-8')
    compile(text,'toolz/itertoolz.py','exec')
    outcomes=groups(source,case['checks'],case['package'],case['source_root'],folder/'logs',('Target','Controls'))
    results[name]={'author':'offline analyst; not Agent or Harness2',
        'source_sha256':sha(source/'toolz/itertoolz.py'),'syntax_compiles':True,
        'iteritems_calls':text.count('iteritems(d)'),
        'groups':outcomes,'all_passed':all(g['passed'] for g in outcomes.values())}
    print(name,results[name]['all_passed'],flush=True)
assert results['candidate_unchanged']['groups']['Target']['errors']==1
assert results['candidate_names_only']['groups']['Target']['failures']==1
assert results['candidate_names_and_duplicate']['all_passed']
assert before=={str(p):sha(p) for p in protected}
rollouts=[]
for label in ('base1','inv1','dom1','agg1'):
    folder=trial/'executions/issue-cc-agg1/toolz-join-unmatched'/label/'agent'
    report=read(folder/'report.json')
    actions=read(folder/'actions.json')
    reads=[a for a in actions if a.get('action')=='read_symbol' and a.get('result',{}).get('complete_symbol')]
    calls=[a for a in actions if a.get('status') in ('completed','tool_error')]
    rollouts.append({'label':label,'status':report['status'],'calls':report['fresh_model_calls'],
        'tokens':report['metrics']['budget_accounted_tokens'],'seconds':report['seconds'],
        'patch_sha256':report['patch_sha256'],'nonempty_patch':bool(report['changed_files']),
        'tool_executions':len(calls),'tool_errors':sum(a['status']=='tool_error' for a in calls),
        'guard_stops':sum(a['status']=='stopped' for a in actions),
        'complete_symbol_reads':[{'step':a['step'],'symbol':a['result']['symbol'],
             'start_line':a['result']['start_line'],'end_line':a['result']['end_line'],
             'characters':len(a['result']['content']),'contains_iteritems':'iteritems(d)' in a['result']['content']}
             for a in reads],
        'candidate_input_contains_iteritems':any('iteritems(d)' in f['content'] for f in
            json.loads(read(sorted(folder.glob('step-*-messages.json'))[-1])[-1]['content']).get('current_fragments',[]))})
audit={'scope':'Single known-task, single-run post-hoc audit; not a strategy efficacy estimate',
    'new_model_calls':0,'diagnostic_patch_author':'offline analyst; not an Agent success',
    'original_source_sha256':sha(trial/'input/toolz/itertoolz.py'),
    'source_contains_iteritems_before_agent':True,'candidate_repeats_existing_unmatched_loop':True,
    'rollouts':rollouts,'counterfactuals':results,'protected_artifacts_unchanged':before}
(out/'audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
print('Audit completed; no model calls; protected artifacts unchanged')
