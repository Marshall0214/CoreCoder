import copy
import json
import sys
from types import SimpleNamespace

import pytest

from corecoder.llm import LLMResponse
from docs.experiments import function_index_audit_v1 as functions
from docs.experiments import repair_hypothesis_v1 as planning
from docs.experiments import repair_hypothesis_worker_v1 as worker
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.schema import RunConfig

CODE='''class Contract:
    def test_none(self):
        self.assertEqual(1, 2)
    def test_default(self):
        self.assertEqual(1, 1)
'''


def observation(names=('test_none',)):
    return {'complete':True,'phase':'execution','tests_run':2,'skipped':0,
            'expected_failures':0,'unexpected_successes':0,
            'issues':[{'test':f'{name} (test_admission.Contract.{name}) (salt=None)', 'kind':'assertion'} for name in names]}


def evidence(root):
    index=functions.FunctionIndex(root,['app.py']); index.refresh()
    return functions.pack(index,index.rank('f'))['evidence']


def proposal():
    return {'hypotheses':[{'tests':['Contract.test_none'],'symbols':['app.py:f'],'claim':'f returns the required value.'}],
            'edits':[{'file':'app.py','old':'return 1','new':'return 2'}]}


def test_subtests_grouped_with_public_code_hash():
    result=planning.diagnose(CODE,observation(('test_none','test_none')))
    assert result['required_failures']==[{'test':'Contract.test_none','assertions':2,'exceptions':0}]
    assert result['other_public_tests']==['Contract.test_default']
    assert len(result['public_check_sha256'])==64


@pytest.mark.parametrize('mutation',[{'complete':False},{'phase':'discovery'},{'tests_run':0},{'skipped':1},
                                     {'issues':[]},{'issues':[{'test':'unknown','kind':'exception'}]}])
def test_invalid_observation_stops(mutation):
    with pytest.raises(planning.InvalidHypothesis):
        planning.diagnose(CODE,dict(observation(),**mutation))


def test_failed_method_limit_records_omissions():
    result=planning.diagnose(CODE,observation(('test_none','test_default')),max_tests=1)
    assert len(result['required_failures'])==1 and result['omitted_failure_methods']==1


def test_valid_proposal_unwraps_exact_patch(tmp_path):
    (tmp_path/'app.py').write_text('def f():\n    return 1\n',encoding='utf-8')
    value=proposal()
    patch,hypotheses=planning.validate(json.dumps(value),evidence(tmp_path),planning.diagnose(CODE,observation()))
    assert json.loads(patch)=={'edits':value['edits']} and hypotheses==value['hypotheses']


@pytest.mark.parametrize('field,value',[('tests',['Unknown.test_none']),('symbols',['app.py:unknown']),
                                      ('claim',''),('claim','x'*501),('tests',[]),('symbols',['app.py:f','app.py:f'])])
def test_invalid_hypothesis_references(tmp_path,field,value):
    (tmp_path/'app.py').write_text('def f():\n    return 1\n',encoding='utf-8')
    data=proposal(); data['hypotheses'][0][field]=value
    with pytest.raises(planning.InvalidHypothesis):
        planning.validate(json.dumps(data),evidence(tmp_path),planning.diagnose(CODE,observation()))


def test_uncovered_failure_and_unbacked_edit_rejected(tmp_path):
    (tmp_path/'app.py').write_text('def f():\n    return 1\n',encoding='utf-8')
    rows=evidence(tmp_path)
    with pytest.raises(planning.InvalidHypothesis,match='not covered'):
        planning.validate(json.dumps(proposal()),rows,planning.diagnose(CODE,observation(('test_none','test_default'))))
    value=proposal(); value['edits'][0]['old']='omitted source'
    with pytest.raises(planning.InvalidHypothesis,match='not backed'):
        planning.validate(json.dumps(value),rows,planning.diagnose(CODE,observation()))


def test_claim_text_is_not_treated_as_semantic_proof():
    hypotheses=proposal()['hypotheses']
    failed={'observation':observation()}
    passed={'observation':observation(())}
    assert planning.assess(hypotheses,CODE,failed)[0]['status']=='failed_public_checks'
    assert planning.assess(hypotheses,CODE,passed)[0]['status']=='supported_on_public_checks'
    passed['observation']['skipped']=1
    assert planning.assess(hypotheses,CODE,passed)[0]['status']=='unverified'


@pytest.mark.parametrize('valid',[True,False])
def test_hypothesis_validation_precedes_transaction(tmp_path,monkeypatch,valid):
    root=tmp_path/'workspace'; root.mkdir(); (root/'app.py').write_text('def f():\n    return 1\n',encoding='utf-8')
    rows=evidence(root); seen=[]; messages=[]
    value=proposal()
    if not valid: value['hypotheses'][0]['symbols']=['app.py:missing']
    class LLM:
        def chat(self,data,tools):
            messages.append(data)
            return SimpleNamespace(content=json.dumps(value),tool_calls=[])
    def transact(patch,*args):
        seen.append(json.loads(patch)); return {'accepted':True,'changed_files':[]}
    monkeypatch.setattr(worker.guard,'transact',transact)
    job={'task_id':'other','allowed_files':['app.py'],'description':'f', 'context_policy':'source-contract',
         'retention_policy':'edited-first','planning_policy':'public-hypotheses', 'test_python':sys.executable,'imports':[]}
    feedback={'repair_diagnostic':planning.diagnose(CODE,observation())}
    result=worker.request_guarded(LLM(),root,job,rows,Events(tmp_path/'trace.jsonl','test'),'feedback',feedback,'public')
    assert ('hypotheses' in messages[0][0]['content'])
    assert result['status']==('completed' if valid else 'hypothesis_rejected')
    assert len(seen)==int(valid)
    if valid: assert seen[0]=={'edits':value['edits']}


def test_initial_messages_identical_between_arms(tmp_path,monkeypatch):
    root=tmp_path/'workspace'; root.mkdir(); (root/'app.py').write_text('def f():\n    return 1\n',encoding='utf-8')
    hashes=[]
    class LLM:
        def chat(self,data,tools): return SimpleNamespace(content='{"edits":[]}',tool_calls=[])
    monkeypatch.setattr(worker.guard,'transact',lambda *args:{'accepted':True,'changed_files':[]})
    for policy in ('patch-only','public-hypotheses'):
        folder=tmp_path/policy; folder.mkdir()
        job={'task_id':'other','allowed_files':['app.py'],'description':'f','context_policy':'source-contract',
             'retention_policy':'edited-first','planning_policy':policy,'test_python':sys.executable,'imports':[]}
        result=worker.request_guarded(LLM(),root,job,evidence(root),Events(folder/'trace.jsonl',policy),'initial')
        hashes.append(result['prompt_hash'])
    assert hashes[0]==hashes[1]


@pytest.mark.parametrize('budget',[15000,1800])
def test_one_feedback_and_shared_budget(tmp_path,monkeypatch,budget):
    root=tmp_path/'workspace'; root.mkdir(); path=root/'app.py'; path.write_text('def f():\n    return 1\n',encoding='utf-8')
    harness=tmp_path/'harness'; harness.mkdir(); canonical=harness/'test_admission.py'; canonical.write_text(CODE,encoding='utf-8')
    monkeypatch.setattr(worker,'canonical_check',lambda task:canonical)
    outcome={'assertion_failure':True,'passed':False,'execution_error':False,'timed_out':False,'tests_run':2,
             'classification':'assertion_failure','observation':observation()}
    sequence=iter([copy.deepcopy(outcome),copy.deepcopy(outcome),dict(outcome,passed=True,assertion_failure=False,
                   classification='passed',observation=observation(()))])
    monkeypatch.setattr(worker.observer,'check_public',lambda *args:(next(sequence),'public failure'))
    class Raw:
        model='test'
        def __init__(self): self.messages=[]
        def chat(self,messages,tools=None):
            self.messages.append(messages)
            old,new=('return 1','return 2') if len(self.messages)==1 else ('return 2','return 3')
            value={'edits':[{'file':'app.py','old':old,'new':new}]}
            if len(self.messages)==2: value['hypotheses']=proposal()['hypotheses']
            tokens=100 if budget==15000 else 700
            return LLMResponse(content=json.dumps(value),prompt_tokens=tokens,completion_tokens=tokens)
    raw=Raw(); events=Events(tmp_path/'trace.jsonl','test'); llm=BudgetLLM(raw,RunConfig(token_budget=budget,max_output_tokens=256),events)
    job={'workspace':str(root),'task_id':'click-usage-empty','description':'f must return 3','allowed_files':['app.py'],
         'evidence':evidence(root),'harness':str(harness),'harness_hash':'mocked','check_code_hash':worker.repair.audit.sha(canonical),
         'test_python':sys.executable,'imports':[{'module':'app','root':'.','path':'app.py'}],'policy':'unified-feedback',
         'context_policy':'source-contract','feedback_policy':'runtime-feedback','retention_policy':'edited-first','planning_policy':'public-hypotheses'}
    if budget==1800:
        with pytest.raises(BudgetExceeded): worker.run_candidate(llm,job,events)
        assert len(raw.messages)==1
    else:
        result=worker.run_candidate(llm,job,events)
        assert len(raw.messages)==2 and result['feedback_attempts']==1
        assert result['stages'][-1]['hypothesis_outcomes'][0]['status']=='supported_on_public_checks'
        assert llm.metrics()['budget_accounted_tokens']==400
