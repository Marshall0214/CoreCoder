import json

import pytest

from repairflow import issue_repair as module
from repairflow.bundles import read, write
from tests import test_issue_repair as fixtures
from tests.issue_repair_fixture import SOURCE, patch


@pytest.fixture
def task(tmp_path, monkeypatch):
    # Reuse the existing prepared task and explicit fake sandbox, without cloud calls.
    return fixtures.task.__wrapped__(tmp_path, monkeypatch)


def action(name, **args):
    return json.dumps({'action': name, 'arguments': args})


def symbol_read(symbol='f', **kwargs):
    return action('read_symbol', path='src/pkg/__init__.py', symbol=symbol, **kwargs)


def execute(tmp_path, task, rows, **kwargs):
    response = tmp_path / 'responses.json'
    write(response, rows)
    return module.execute(*task, tmp_path / 'run', mode='scripted', responses=response,
                          workflow='symbol-recovery-v1', **kwargs)


def test_third_edit_after_explicit_reads_succeeds_with_structured_feedback(tmp_path, task):
    bad = patch(old=77)
    report = execute(tmp_path, task, [bad, symbol_read(), bad, symbol_read(), patch()])
    assert report['public_checks_passed'] and not report['accepted']
    assert report['scripted_calls'] == 5 and report['edit_attempts_used'] == 3
    assert report['attempts'][0]['error']['code'] == 'anchor_not_found'
    assert report['attempts'][0]['error']['next_action'] == 'read_symbol'
    assert report['actions'][1]['result']['content'].startswith('def f(x):')
    payload = json.loads(read(tmp_path / 'run/step-003-messages.json')[1]['content'])
    assert payload['must_read_before_edit'] == []
    assert 'anchor_not_found' in json.dumps(payload['observations'])
    assert read(tmp_path / 'run/actions.json') == report['actions']
    assert report['original_unchanged'] and report['fresh_model_calls'] == 0
    assert read(tmp_path / 'run/provenance.json')['limits']['max_rounds'] == 20


def test_rejected_anchor_requires_read_before_retry(tmp_path, task):
    report = execute(tmp_path, task, [patch(old=77), patch(), symbol_read(), patch()])
    assert report['public_checks_passed'] and report['scripted_calls'] == 4
    assert report['attempts'][1]['error']['code'] == 'read_required'


def test_read_after_failed_public_checks_uses_modified_source(tmp_path, task):
    report = execute(tmp_path, task, [patch(new=4), symbol_read(), patch(old=4)])
    assert report['public_checks_passed']
    row = report['actions'][1]['result']
    assert 'return x + 4' in row['content']
    assert row['content_hash'] != read(tmp_path / 'run/agent-initial-context.json')['evidence'][0]['content_hash']
    payload = json.loads(read(tmp_path / 'run/step-003-messages.json')[1]['content'])
    assert 'public_validation_failed' in json.dumps(payload['observations'])
    assert 'AssertionError' in json.dumps(payload['observations'])


def test_compact_history_retains_current_source_errors_feedback_and_full_report(tmp_path, task):
    report = execute(tmp_path, task, [symbol_read(), patch(old=77), symbol_read(), patch(new=4),
                                     symbol_read(), patch(old=4)], observation_policy='compact-v1')
    assert report['public_checks_passed'] and not report['accepted']
    assert report['scripted_calls'] == 6 and report['edit_attempts_used'] == 3
    assert report['observation_policy'] == 'compact-v1'
    assert read(tmp_path / 'run/provenance.json')['observation_policy'] == 'compact-v1'
    payload = json.loads(read(tmp_path / 'run/step-006-messages.json')[1]['content'])
    assert payload['must_read_before_edit'] == []
    assert any('return x + 4' in row['content'] for row in payload['fragments'])
    assert payload['observations'][0]['result']['content_available'] is False
    assert payload['observations'][4]['result']['content_available'] is True
    assert payload['observations'][1]['error']['code'] == 'anchor_not_found'
    assert 'AssertionError' in payload['observations'][3]['public_check_feedback']['observations']
    assert all('content' not in row.get('result', {}) for row in payload['observations'])
    # Full source and proposed old/new text remain in reports, not the request projection.
    assert report['actions'][0]['result']['content'].startswith('def f(x):')
    assert 'old' in report['actions'][1]['arguments']['edits'][0]
    assert read(tmp_path / 'run/actions.json') == report['actions']


@pytest.mark.parametrize('option,rows,status', [
    ({'max_steps': 1}, [symbol_read()], 'step_limit'),
    ({'max_edit_attempts': 3}, [patch(old=77), symbol_read(), patch(old=77), symbol_read(), patch(old=77)], 'edit_attempt_limit'),
    ({'max_consecutive_errors': 2}, ['{}', '{}'], 'consecutive_error_limit'),
    ({'max_repeated_actions': 2}, [symbol_read(), symbol_read(), symbol_read()], 'repeated_action_limit'),
])
def test_configured_stop_reasons_are_explicit_and_roll_back(tmp_path, task, option, rows, status):
    report = execute(tmp_path, task, rows, **option)
    assert report['status'] == status and not report['public_checks_passed']
    assert report['candidate_rolled_back'] and (tmp_path / 'run/patch.diff').read_text() == ''
    assert (tmp_path / 'run/workspace/src/pkg/__init__.py').read_text() == SOURCE


def test_finish_cannot_claim_success(tmp_path, task):
    report = execute(tmp_path, task, [action('finish')])
    assert report['status'] == 'agent_finished_without_verified_patch'
    assert report['accepted'] is False and not report['public_checks_passed']


def test_nonretryable_path_error_stops_without_further_generation(tmp_path, task):
    report = execute(tmp_path, task, [action('read_symbol', path='../secret.py', symbol='f'), patch()])
    assert report['status'] == 'nonretryable_tool_error' and report['scripted_calls'] == 1
    assert report['actions'][0]['error']['code'] == 'path_not_allowed'


def test_exhausted_script_is_not_a_model_or_code_failure(tmp_path, task):
    report = execute(tmp_path, task, [symbol_read()])
    assert report['status'] == 'scripted_responses_exhausted'
    assert report['actions'][-1]['status'] == report['status']
    assert read(tmp_path / 'run/actions.json')[-1]['status'] == report['status']


def test_explicit_reads_work_when_initial_pack_is_unavailable(tmp_path, task, monkeypatch):
    from repairflow import issue_agent

    monkeypatch.setattr(issue_agent, 'baseline_retrieve', lambda *a: (_ for _ in ()).throw(ValueError('coverage budget')))
    report = execute(tmp_path, task, [symbol_read(), patch()])
    assert report['public_checks_passed']
    assert read(tmp_path / 'run/agent-initial-context.json')['evidence'] == []


def test_budget_stop_is_reported_and_rolls_back(tmp_path, task, monkeypatch):
    from evals.runtime import BudgetExceeded

    def exhausted(*args, **kwargs):
        raise BudgetExceeded('preflight')

    monkeypatch.setattr(module.BudgetLLM, 'chat', exhausted)
    report = execute(tmp_path, task, [symbol_read()])
    assert report['status'] == 'budget_exceeded' and report['candidate_rolled_back']
    assert read(tmp_path / 'run/actions.json')[-1]['status'] == 'budget_exceeded'


def test_sandbox_fault_stops_without_treating_it_as_patch_feedback(tmp_path, task, monkeypatch):
    from sandbox import runner

    real = runner.run

    def fail(*args):
        if args[4].name != 'baseline':
            raise runner.SandboxError('sandbox_timeout')
        return real(*args)

    monkeypatch.setattr(runner, 'run', fail)
    report = execute(tmp_path, task, [patch(new=4), symbol_read(), patch(old=4)])
    assert report['status'] == 'sandbox_timeout' and report['scripted_calls'] == 1
    assert report['candidate_rolled_back'] and (tmp_path / 'run/patch.diff').read_text() == ''


def test_tests_not_executed_stop_the_loop(tmp_path, task, monkeypatch):
    real = module.public_checks

    def incomplete(workspace, harness, task, logs, *rest):
        outcomes = real(workspace, harness, task, logs, *rest)
        if logs.name != 'baseline':
            outcomes['Reproduce'].update(tests_run=0, passed=False)
        return outcomes

    monkeypatch.setattr(module, 'public_checks', incomplete)
    report = execute(tmp_path, task, [patch(new=4), symbol_read()])
    assert report['status'] == 'public_check_execution_failed' and report['scripted_calls'] == 1
    assert report['candidate_rolled_back']


def test_cli_exposes_retry_overrides_and_new_default(tmp_path, task, monkeypatch, capsys):
    import sys

    from repairflow import __main__ as cli

    responses = tmp_path / 'responses.json'
    write(responses, [patch(old=77), symbol_read(), patch(old=77), symbol_read(), patch()])
    monkeypatch.setattr(sys, 'argv', ['repairflow', 'repair-issue', '--prepared', str(task[0]), '--config', str(task[1]),
                                    '--output', str(tmp_path / 'run'), '--mode', 'scripted', '--responses', str(responses),
                                    '--max-steps', '12', '--max-edit-attempts', '4', '--observation-policy', 'compact-v1'])
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)['public_checks_passed']
    provenance = read(tmp_path / 'run/provenance.json')
    assert provenance['workflow'] == 'symbol-recovery-v1'
    assert provenance['recovery_limits']['max_edit_attempts'] == 4
    assert provenance['limits']['max_rounds'] == 12
    assert provenance['observation_policy'] == 'compact-v1'


@pytest.mark.parametrize('workflow,policy', [('symbol-recovery-v1', 'unknown'), ('patch-v1', 'compact-v1')])
def test_observation_policy_rejected_before_loading_inputs(tmp_path, workflow, policy):
    with pytest.raises(ValueError, match='observation|Compact'):
        module.execute(tmp_path / 'missing', tmp_path / 'missing.json', tmp_path / 'run', mode='ollama',
                       workflow=workflow, observation_policy=policy)


@pytest.mark.parametrize('option', [{'max_steps': 0}, {'max_edit_attempts': -1}, {'max_consecutive_errors': True},
                                   {'max_repeated_actions': 101}])
def test_invalid_limits_rejected_before_loading_inputs(tmp_path, option):
    with pytest.raises(ValueError, match='integer'):
        module.execute(tmp_path / 'missing', tmp_path / 'missing.json', tmp_path / 'run', mode='ollama', **option)
