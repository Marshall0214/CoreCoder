import hashlib
import json
import sys

import pytest

from corecoder.llm import LLMResponse
from docs.experiments import function_index_audit_v1 as functions
from docs.experiments import tentative_feedback_worker_v1 as worker
from evals.runtime import BudgetLLM, Events
from evals.schema import RunConfig

CODE='''import unittest
from pkg import f
class PublicContract(unittest.TestCase):
    def test_result(self):
        self.assertEqual(f(), 3)
'''


def setup(tmp_path,monkeypatch,replies,budget=15000):
    root=tmp_path/'workspace'; path=root/'src/pkg/__init__.py'; path.parent.mkdir(parents=True)
    path.write_text('def f():\n    return 1\n',encoding='utf-8')
    harness=tmp_path/'harness'; harness.mkdir(); canonical=tmp_path/'canonical.py'; canonical.write_text(CODE,encoding='utf-8')
    (harness/'test_admission.py').write_bytes(canonical.read_bytes())
    monkeypatch.setattr(worker.tentative,'canonical_check',lambda task:canonical)
    index=functions.FunctionIndex(root,['src/pkg/__init__.py']); index.refresh()
    artifact=tmp_path/'run'; artifact.mkdir(); events=Events(artifact/'trace.jsonl','tentative-test')
    class Raw:
        model='test'
        def __init__(self): self.messages=[]
        def chat(self,messages,tools=None):
            assert path.read_text()=='def f():\n    return 1\n'  # Neither request sees a published first patch.
            self.messages.append(messages)
            old,new=replies[len(self.messages)-1]
            tokens=100 if budget==15000 else 700
            return LLMResponse(content=json.dumps({'edits':[{'file':'src/pkg/__init__.py','old':old,'new':new}]}),
                               prompt_tokens=tokens,completion_tokens=tokens)
    raw=Raw(); llm=BudgetLLM(raw,RunConfig(token_budget=budget,max_output_tokens=256),events)
    job={'workspace':str(root),'task_id':'pkg','description':'f must return 3.','allowed_files':['src/pkg/__init__.py'],
         'evidence':functions.pack(index,index.rank('f'))['evidence'],'harness':str(harness),
         'harness_hash':worker.repair.digest(worker.repair.snapshot(harness)),
         'check_code_hash':hashlib.sha256(canonical.read_bytes()).hexdigest(), 'test_python':sys.executable,
         'imports':[{'module':'pkg','root':'src','path':'src/pkg/__init__.py'}], 'policy':'unified-feedback',
         'retention_policy':'edited-first','feedback_policy':'runtime-feedback','context_policy':'source-contract'}
    return root,job,events,llm,raw


def test_first_correct_patch_publishes_once(tmp_path,monkeypatch):
    root,job,events,llm,raw=setup(tmp_path,monkeypatch,[('return 1','return 3')])
    result=worker.run_candidate(llm,job,events)
    assert result['committed'] and len(raw.messages)==1
    assert result['feedback_attempts']==0 and result['lifecycle'][-1]=='committed'
    assert (root/'src/pkg/__init__.py').read_text()=='def f():\n    return 3\n'


@pytest.mark.parametrize('initial',['return 2',"raise TypeError('candidate')",'return ('])
def test_feedback_repairs_tentative_source_then_publishes(tmp_path,monkeypatch,initial):
    old='return 1' if initial=='return (' else initial
    root,job,events,llm,raw=setup(tmp_path,monkeypatch,[('return 1',initial),(old,'return 3')])
    result=worker.run_candidate(llm,job,events)
    assert result['committed'] and len(raw.messages)==2 and result['feedback_attempts']==1
    second=json.loads(raw.messages[1][1]['content'])
    assert old in second['fragments'][0]['content']
    assert llm.metrics()['budget_accounted_tokens']==400
    assert (root/'src/pkg/__init__.py').read_text()=='def f():\n    return 3\n'


@pytest.mark.parametrize('final',['return 4','return ('])
def test_final_failure_keeps_task_start_and_diagnostics(tmp_path,monkeypatch,final):
    root,job,events,llm,raw=setup(tmp_path,monkeypatch,[('return 1','return 2'),('return 2',final)])
    before=worker.gate.structural.files(root)
    result=worker.run_candidate(llm,job,events)
    assert not result['committed'] and result['original_unchanged'] and result['edited_files']==[]
    assert worker.gate.structural.files(root)==before and len(raw.messages)==2
    assert (events.path.parent/'tentative-source').exists() and (events.path.parent/'lifecycle.json').exists()
    if final=='return 4': assert result['status']=='public_check_failed'
    else: assert result['status']=='invalid_python'


def test_budget_stop_preserves_task_start(tmp_path,monkeypatch):
    _root,job,events,llm,raw=setup(tmp_path,monkeypatch,[('return 1','return 2')],budget=1800)
    result=worker.run_candidate(llm,job,events)
    assert result['status']=='budget_exceeded' and result['original_unchanged'] and len(raw.messages)==1
    assert 'return 2' in (events.path.parent/'tentative-source/src/pkg/__init__.py').read_text()


def test_provider_exception_preserves_task_start(tmp_path,monkeypatch):
    _root,job,events,llm,raw=setup(tmp_path,monkeypatch,[('return 1','return 2')])
    real=raw.chat
    def fail(messages,tools=None):
        if raw.messages: raise RuntimeError('provider unavailable')
        return real(messages,tools)
    monkeypatch.setattr(raw,'chat',fail)
    result=worker.run_candidate(llm,job,events)
    assert result['status']=='agent_error' and result['original_unchanged'] and not result['committed']


def test_missing_public_checks_stops_without_model_call(tmp_path,monkeypatch):
    _root,job,events,llm,raw=setup(tmp_path,monkeypatch,[])
    monkeypatch.setattr(worker.tentative,'canonical_check',lambda task:None)
    result=worker.run_candidate(llm,job,events)
    assert result['status']=='no_certified_public_checks' and not raw.messages and result['original_unchanged']


def test_external_source_edit_is_preserved(tmp_path,monkeypatch):
    root,job,events,llm,raw=setup(tmp_path,monkeypatch,[('return 1','return 3')])
    real=raw.chat
    def mutate(messages,tools=None):
        response=real(messages,tools); (root/'src/pkg/__init__.py').write_text('def f():\n    return 99\n',encoding='utf-8'); return response
    monkeypatch.setattr(raw,'chat',mutate)
    result=worker.run_candidate(llm,job,events)
    assert result['status']=='source_changed' and not result['committed'] and not result['original_unchanged']
    assert 'return 99' in (root/'src/pkg/__init__.py').read_text()


def test_publication_write_failure_restores_task_start(tmp_path,monkeypatch):
    root,job,events,llm,_raw=setup(tmp_path,monkeypatch,[('return 1','return 3')])
    def fail(path,data):
        path.write_bytes(data)
        raise OSError('partial publication')
    monkeypatch.setattr(worker.gate,'_write',fail)
    result=worker.run_candidate(llm,job,events)
    assert result['status']=='commit_failed' and result['original_unchanged'] and not result['committed']
    assert result['publication']['rollback']['restored'] and result['edited_files']==[]
    assert (root/'src/pkg/__init__.py').read_text()=='def f():\n    return 1\n'


def test_changed_check_stops_before_model(tmp_path,monkeypatch):
    _root,job,events,llm,raw=setup(tmp_path,monkeypatch,[])
    job['check_code_hash']='stale'
    result=worker.run_candidate(llm,job,events)
    assert result['status']=='agent_error' and result['original_unchanged'] and not raw.messages

@pytest.mark.parametrize('change,expected',[('time',True),('test_count',False),('assertion',False),('source',False)])
def test_replay_only_normalizes_public_unittest_timing(change,expected):
    from docs.experiments.tentative_feedback_audit_v1 import normalize_messages
    data={'fragments':[{'content':'return 1'}], 'public_check_feedback':{'output':'AssertionError: 1 != 3\nRan 4 tests in 0.006s'}}
    first=[{'role':'system','content':'fixed'},{'role':'user','content':json.dumps(data)}]
    second=json.loads(json.dumps(data))
    if change=='time': second['public_check_feedback']['output']=second['public_check_feedback']['output'].replace('0.006','0.007')
    elif change=='test_count': second['public_check_feedback']['output']=second['public_check_feedback']['output'].replace('4 tests','3 tests')
    elif change=='assertion': second['public_check_feedback']['output']=second['public_check_feedback']['output'].replace('1 != 3','2 != 3')
    else: second['fragments'][0]['content']='return 2'
    messages=[first[0],{'role':'user','content':json.dumps(second)}]
    assert (normalize_messages(first)==normalize_messages(messages))==expected
