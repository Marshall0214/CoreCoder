import hashlib
import json

import pytest

from evals.budget_diagnostic import first_change_stats
from evals.runtime import Events, make_tools
from evals.schema import RunConfig


def test_actual_change_events_ignore_noops_failed_edits_and_track_reverts(tmp_path):
    source = tmp_path / 'code.py'
    source.write_text('value = 1\n')
    trace = tmp_path / 'trace.jsonl'
    events = Events(trace, 'test')
    tools = {tool.name: tool for tool in make_tools(tmp_path, ['code.py'], events, 5, RunConfig())}
    events.emit('agent_round', round=3)
    events.emit('request_preflight', reservation=500)
    events.emit('llm_started', call_id='llm-1')
    events.emit('llm_finished', call_id='llm-1', usage_known=True, prompt_tokens=100, completion_tokens=40)
    tools['write_file'].execute(file_path='code.py', content='value = 1\n')
    tools['edit_file'].execute(file_path='code.py', old_string='missing', new_string='nothing')
    assert first_change_stats(trace)['first_source_change'] is None
    tools['edit_file'].execute(file_path='code.py', old_string='value = 1', new_string='value = 2')
    tools['write_file'].execute(file_path='code.py', content='value = 1\n')
    first = first_change_stats(trace)['first_source_change']
    assert source.read_text() == 'value = 1\n'
    assert first['tool'] == 'edit_file' and first['agent_round'] == 3
    assert first['known_tokens'] == first['budget_accounted_tokens'] == 140
    changes = [json.loads(line) for line in trace.read_text().splitlines()
               if json.loads(line)['event'] == 'source_changed']
    assert len(changes) == 2


def test_missing_usage_before_change_is_unknown_and_charged_as_reservation(tmp_path):
    trace = tmp_path / 'trace'
    events = Events(trace, 'test')
    events.emit('request_preflight', reservation=700)
    events.emit('llm_started', call_id='llm-1')
    events.emit('llm_finished', call_id='llm-1', usage_known=False)
    events.emit('source_changed', path='code.py', tool='write_file')
    first = first_change_stats(trace)['first_source_change']
    assert first['known_tokens'] == 0
    assert first['budget_accounted_tokens'] == 700 and first['missing_usage_calls'] == 1
    with trace.open('a') as stream:
        stream.write('{partial')
    assert first_change_stats(trace)['partial_trace_lines'] == 1


def test_scripted_trace_does_not_claim_measured_zero_token_usage(tmp_path):
    trace = tmp_path / 'trace'
    events = Events(trace, 'test')
    events.emit('source_changed', path='code.py', tool='write_file')
    first = first_change_stats(trace)['first_source_change']
    assert first['budget_accounted_tokens'] is None and first['known_tokens'] is None


@pytest.mark.parametrize('cancel', [False, True])
def test_diagnostic_matrix_freezes_other_conditions_and_stops_on_cancellation(tmp_path, monkeypatch, cancel):
    from evals.budget_diagnostic import run_diagnostic

    suite = tmp_path / 'suite.json'
    suite.write_text('{}')
    protocol = tmp_path / 'protocol.json'
    protocol.write_text(json.dumps({'schema_version': 1, 'purpose': 'development-budget-diagnosis',
                                   'suite': suite.name, 'suite_sha256': hashlib.sha256(suite.read_bytes()).hexdigest(),
                                   'budgets': [30000, 60000, 100000], 'repeat': 1,
                                   'max_rounds': 32, 'wall_timeout': 600}))
    config = RunConfig(mode='live').to_dict()
    monkeypatch.setattr('evals.budget_diagnostic.load_manifest', lambda path:
                        ({'config': config}, [('one', suite, 'task')]))
    monkeypatch.setattr('evals.budget_diagnostic.prepare', lambda entries, admissions:
                        [(None, None, tmp_path / 'checks', tmp_path / 'source', {})])
    calls = []

    def run(manifest, admissions, output, mode, repeat, diagnostic_overrides):
        calls.append(diagnostic_overrides)
        output.mkdir()
        Events(output / 'trace.jsonl', 'test').emit('agent_round', round=1)
        return {'complete': not cancel, 'implementation': {'source_hash': 'same'},
                'config': dict(config, **diagnostic_overrides), 'runs': [
                    {'artifacts': str(output), 'task_id': 'task', 'repetition': 1,
                     'status': 'cancelled' if cancel else 'budget_exceeded', 'accepted': False,
                     'metrics': None, 'seconds': 1, 'verification': None}]}

    monkeypatch.setattr('evals.budget_diagnostic.run_suite', run)
    result = run_diagnostic(protocol, {}, tmp_path / 'out')
    assert result['complete'] is (not cancel)
    assert result['expected_runs'] == 3
    assert result['completed_runs'] == (1 if cancel else 3)
    assert [call['token_budget'] for call in calls] == ([30000] if cancel else [30000, 60000, 100000])
    assert all(call['max_rounds'] == 32 and call['wall_timeout'] == 600 for call in calls)
