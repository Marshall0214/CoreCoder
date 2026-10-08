from types import SimpleNamespace

import pytest

from docs.experiments import verified_correction_retry_v1 as retry
from evals.runner import digest, snapshot
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.schema import RunConfig


def test_inherits_all_known_usage_before_third_request():
    llm = SimpleNamespace(config=SimpleNamespace(token_budget=15000))
    retry.inherit_budget(llm, {'llm_calls': 2, 'missing_usage_calls': 0, 'budget_accounted_tokens': 5270,
                             'known_prompt_tokens': 4292, 'known_completion_tokens': 978})
    assert (llm.calls, llm.spent, llm.prompt_known, llm.completion_known) == (2, 5270, 4292, 978)


@pytest.mark.parametrize('change', [{'llm_calls': 3}, {'missing_usage_calls': 1}, {'budget_accounted_tokens': 15000}])
def test_retry_refuses_extra_calls_or_unknown_exhausted_budget(change):
    metrics = {'llm_calls': 2, 'missing_usage_calls': 0, 'budget_accounted_tokens': 5270,
               'known_prompt_tokens': 4292, 'known_completion_tokens': 978}
    metrics.update(change)
    with pytest.raises(ValueError):
        retry.inherit_budget(SimpleNamespace(config=SimpleNamespace(token_budget=15000)), metrics)


def test_inherited_usage_blocks_third_call_before_provider(tmp_path):
    provider = SimpleNamespace(model='test', chat=lambda *a, **k: pytest.fail('Provider must not be called'))
    llm = BudgetLLM(provider, RunConfig(token_budget=15000, max_output_tokens=2048), Events(tmp_path / 'trace', 'test'))
    retry.inherit_budget(llm, {'llm_calls': 2, 'missing_usage_calls': 0, 'budget_accounted_tokens': 14000,
                             'known_prompt_tokens': 12000, 'known_completion_tokens': 2000})
    with pytest.raises(BudgetExceeded):
        llm.chat([{'role': 'user', 'content': 'fix'}], tools=[])
    assert llm.calls == 2 and llm.spent == 14000


@pytest.mark.parametrize('passed,status', [(True, 'completed'), (False, 'completed'), (False, 'budget_exceeded')])
def test_third_attempt_is_retained_only_after_checks_otherwise_rolls_back(tmp_path, monkeypatch, passed, status):
    workspace, source = tmp_path / 'workspace', tmp_path / 'starting'
    workspace.mkdir()
    source.mkdir()
    (workspace / 'code.py').write_text('rejected')
    (source / 'code.py').write_text('original')
    job = {'workspace': str(workspace), 'original_hash': digest(snapshot(workspace)),
           'starting_source_hash': digest(snapshot(source)), 'evidence': []}
    llm = SimpleNamespace(calls=2)
    llm.metrics = lambda: {'llm_calls': llm.calls}
    groups = lambda ok: {name: {group: {'passed': ok, 'timed_out': False, 'tests_run': 1}
                                 for group in ('Reproduce', 'Preserve')} for name in ('public', 'frozen')}
    monkeypatch.setattr(retry.guarded, 'validate', lambda *a: None)
    def request(*a):
        llm.calls += 1
        (workspace / 'code.py').write_text('corrected')
        return {'status': status}
    monkeypatch.setattr(retry.previous, 'request', request)
    monkeypatch.setattr(retry.guarded, 'checked', lambda *a: groups(passed))
    result = retry.correction(llm, job, groups(False), {}, Events(tmp_path / 'trace', 'test'), source)
    assert result['published'] == passed and llm.calls == 3
    assert (workspace / 'code.py').read_text() == ('corrected' if passed else 'original')
