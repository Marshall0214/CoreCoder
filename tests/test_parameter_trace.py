import json
from pathlib import Path

import pytest

from corecoder.llm import LLMResponse
from docs.experiments import parameter_trace_v1 as tracing
from docs.experiments import parameter_trace_worker_v1 as worker
from docs.experiments import tentative_feedback_worker_v1 as old
from tests.test_tentative_feedback import setup


@pytest.mark.parametrize('policy', ['baseline', 'parameter-trace'])
def test_actual_trace_keeps_public_outcome_and_budget(tmp_path, monkeypatch, policy):
    root, job, events, llm, raw = setup(tmp_path, monkeypatch, [])
    monkeypatch.setattr(worker, 'canonical_check', old.tentative.canonical_check)
    job['trace_policy'] = policy
    def chat(messages, tools=None):
        count = len(raw.messages); raw.messages.append(messages)
        edit = {'file': 'src/pkg/__init__.py', 'old': 'return 1' if not count else 'return 2',
                'new': 'return 2' if not count else 'return 3'}
        return LLMResponse(content=json.dumps({'edits': [edit]}), prompt_tokens=100, completion_tokens=100)
    monkeypatch.setattr(raw, 'chat', chat)
    result = worker.run_candidate(llm, job, events)
    assert result['public_checks']['final']['passed'] and len(raw.messages) == 2
    assert result['parameter_trace_audit']['ordinary_equivalent']
    assert result['parameter_trace_audit']['events'] > 0
    data = json.loads(raw.messages[1][1]['content'])
    if policy == 'parameter-trace':
        assert data['public_check_feedback']['parameter_execution']['events']
        assert result['stages'][-1]['combined_evidence_chars'] <= 6000
    else: assert 'parameter_execution' not in data['public_check_feedback']
    assert llm.metrics()['budget_accounted_tokens'] == 400
    assert 'return 3' in (root/'src/pkg/__init__.py').read_text()


def test_packing_is_bounded_and_failure_only():
    record = {'issues': [{'test':'test_bad (x.PublicContract)'}], 'parameter_trace': [
        {'test':'x.PublicContract.test_good','values':{'salt':'unrelated'}},
        {'test':'x.PublicContract.test_bad','values':{'salt':None}}]*20}
    value = tracing.pack(record, 600)
    assert len(json.dumps(value, ensure_ascii=False)) <= 600
    assert value['omitted_events'] > 0
    assert all(r['test'].endswith('test_bad') for r in value['events'])
    assert tracing.pack(record, 1) is None


def test_changed_public_outcome_is_detected():
    left = {'complete':True, 'successful':False, 'tests_run':1,'issues':[]}
    assert not tracing.equivalent(left, dict(left, successful=True))


def test_safe_values_do_not_call_repr_or_capture_secrets():
    # Execute the same helper used by the isolated observer.
    setup_code = tracing.TRACE_SETUP.split('def trace(')[0]
    namespace = {'json':json, 'pathlib':__import__('pathlib'), 'sys':type('Args',(),{'argv':[0]*5+[str(Path(__file__))]})}
    setup_code = setup_code[setup_code.index('active_test,'):]
    exec(setup_code, namespace)  # noqa: S102 - fixed observer helper under test
    class Secret:
        def __repr__(self): raise AssertionError('repr must not run')
    assert namespace['safe'](Secret()) == {'type':'<unrecorded>'}
    assert namespace['safe'](b'abc') == {'type':'bytes','hex':'616263','truncated':False}
    assert len(namespace['safe']('x'*100)['value']) == 64
    assert 'secret_key' not in tracing.WATCH and 'secret_keys' not in tracing.ATTRS
