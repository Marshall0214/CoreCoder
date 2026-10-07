import hashlib
import json
import sys
from pathlib import Path

import pytest

from corecoder.llm import LLMResponse
from docs.experiments import runtime_feedback_worker_v1 as worker
from docs.experiments import runtime_observation_v1 as observer
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.schema import RunConfig


def check(tmp_path, code='return 1', tests='self.assertEqual(pkg.f(), 1)', before=''):
    workspace = tmp_path/'workspace'
    package = workspace/'src/pkg'
    package.mkdir(parents=True)
    (package/'__init__.py').write_text('def f():\n    '+code+'\n', encoding='utf-8')
    harness = tmp_path/'harness'
    harness.mkdir()
    (harness/'test_admission.py').write_text('import unittest\nimport pkg\n'+before+
        '\nclass PublicContract(unittest.TestCase):\n    def test_public(self):\n        '+tests+'\n', encoding='utf-8')
    value = observer.public.repair.digest(observer.public.repair.snapshot(harness))
    return observer.check_public(workspace, harness, value, tmp_path/'run', Path(sys.executable), 'pkg')


@pytest.mark.parametrize('code,tests,expected', [
    ('return 1', 'self.assertEqual(pkg.f(), 1)', 'passed'),
    ('return 1', 'self.assertEqual(pkg.f(), 3)', 'assertion_failure'),
    ('return None + b"x"', 'pkg.f()', 'candidate_runtime_error'),
    ('return object().missing', 'pkg.f()', 'candidate_runtime_error'),
    ('return 1', 'missing_harness_name()', 'harness_or_unknown_error'),
    ('return None + b"x"', 'with self.subTest(case="runtime"):\n            pkg.f()', 'candidate_runtime_error'),
    ('return None + b"x"', 'with self.subTest(case="assertion"):\n            self.assertEqual(1,2)\n        with self.subTest(case="runtime"):\n            pkg.f()', 'candidate_runtime_error'),
    ('return 1', 'with self.subTest(case="assertion"):\n            self.assertEqual(1,2)\n        with self.subTest(case="harness"):\n            missing_harness_name()', 'harness_or_unknown_error'),
    ('return 1', 'self.skipTest("unavailable")', 'inconclusive_tests'),
])
def test_real_test_runner_classifies_origins_and_subtests(tmp_path, code, tests, expected):
    outcome, _ = check(tmp_path, code, tests)
    assert outcome['classification'] == expected
    assert observer.recoverable(outcome) == (expected in {'assertion_failure', 'candidate_runtime_error'})
    if expected == 'candidate_runtime_error':
        issue = next(i for i in outcome['observation']['issues'] if i['origin']=='candidate')
        assert issue['frames'][-1]['path'] == 'pkg/__init__.py' and issue['frames'][-1]['line'] == 2


def test_discovery_fault_never_enters_candidate_feedback(tmp_path):
    outcome, _ = check(tmp_path, before='raise RuntimeError("broken harness discovery")')
    assert outcome['classification'] == 'observer_failure' and not observer.recoverable(outcome)


def test_source_mutation_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='mutated'):
        check(tmp_path, code='__import__("pathlib").Path(__file__).write_text("changed"); return 1', tests='pkg.f()')


@pytest.mark.parametrize('record,process,category', [
    (None, {'timed_out':False,'returncode':1}, 'observer_failure'),
    ([], {'timed_out':False,'returncode':1}, 'observer_failure'),
    ({'version':1,'complete':True,'tests_run':0,'issues':[]}, {'timed_out':False,'returncode':1}, 'no_tests'),
    (None, {'timed_out':True,'returncode':-1}, 'timeout'),
    ({'version':1,'complete':True,'tests_run':1,'issues':[None]}, {'timed_out':False,'returncode':1}, 'observer_failure'),
])
def test_missing_incomplete_or_invalid_observation_is_not_recoverable(record, process, category):
    assert observer.classify(record, process) == category


def workflow(tmp_path, monkeypatch, policy, classification, budget=15000):
    workspace = tmp_path/'workspace'
    workspace.mkdir()
    path = workspace/'app.py'
    path.write_text('def f():\n    return 1\n', encoding='utf-8')
    harness = tmp_path/'harness'
    harness.mkdir()
    canonical = harness/'test_admission.py'
    canonical.write_text('# public-only check\n', encoding='utf-8')
    monkeypatch.setattr(worker, 'canonical_check', lambda task:canonical)
    first = {'assertion_failure':True,'passed':False,'execution_error':False,'timed_out':False,'tests_run':1,
             'classification':'assertion_failure','observation':{'issues':[]}}
    candidate = dict(first, classification=classification, execution_error=True,
                     observation={'issues':[{'kind':'exception','origin':'candidate','exception_type':'TypeError'}]})
    sequence = iter([first,candidate,dict(first,passed=True,assertion_failure=False,classification='passed')])
    monkeypatch.setattr(worker.observer, 'check_public', lambda *args:(next(sequence),'Public candidate error'))
    def evidence():
        data=path.read_bytes()
        return [{'path':'app.py','symbol':'f','start_line':1,'end_line':2,'content':data.decode(),
                 'content_hash':hashlib.sha256(data).hexdigest()}]
    monkeypatch.setattr(worker, 'pack_feedback', lambda workspace,job:{'evidence':evidence(),'metadata':{'refreshed':True}})
    class LLM:
        model='test'
        def __init__(self):
            self.messages=[]
        def chat(self,messages,tools=None):
            self.messages.append(messages)
            old,new=('return 1','return 2') if len(self.messages)==1 else ('return 2','return 3')
            return LLMResponse(content=json.dumps({'edits':[{'file':'app.py','old':old,'new':new}]}),
                               prompt_tokens=100 if budget==15000 else 700,completion_tokens=100 if budget==15000 else 700)
    raw=LLM(); raw.messages=[]
    events=Events(tmp_path/'trace.jsonl',policy)
    llm=BudgetLLM(raw,RunConfig(token_budget=budget,max_output_tokens=256),events)
    job={'workspace':str(workspace),'task_id':'click-usage-empty','description':'f must return 3.',
         'allowed_files':['app.py'],'evidence':evidence(),'harness':str(harness),'harness_hash':'mocked',
         'check_code_hash':worker.repair.audit.sha(canonical),'test_python':sys.executable,
         'imports':[{'module':'app','root':'.','path':'app.py'}],'policy':'unified-feedback',
         'context_policy':'source-contract','feedback_policy':policy}
    return llm, raw, job, events


@pytest.mark.parametrize('policy,category,calls', [('assertion-only','candidate_runtime_error',1),
                                               ('runtime-feedback','candidate_runtime_error',2),
                                               ('runtime-feedback','harness_or_unknown_error',1),
                                               ('runtime-feedback','timeout',1)])
def test_runtime_feedback_gate_uses_existing_one_retry_only(tmp_path,monkeypatch,policy,category,calls):
    llm,raw,job,events=workflow(tmp_path,monkeypatch,policy,category)
    result=worker.run_candidate(llm,job,events)
    assert len(raw.messages)==calls and result['feedback_attempts']==calls-1
    if calls==2:
        data=json.loads(raw.messages[1][1]['content'])
        assert data['public_check_feedback']['runtime_observation']['classification']==category
        assert 'return 2' in data['fragments'][0]['content'] and result['public_checks']['final']['passed']
        assert llm.metrics()['budget_accounted_tokens']==400


def test_runtime_feedback_shares_cumulative_budget(tmp_path,monkeypatch):
    llm,raw,job,events=workflow(tmp_path,monkeypatch,'runtime-feedback','candidate_runtime_error',budget=1800)
    with pytest.raises(BudgetExceeded):
        worker.run_candidate(llm,job,events)
    assert len(raw.messages)==1
