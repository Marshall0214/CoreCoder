"""No inference: denominator, missing costs, and historical-control execution guard."""
import harness2_rerun50_20261106 as rerun

from integrations import harness2 as bridge
from integrations import harness2_batch as batch
from tests.test_harness2_batch import fixture


def test_flow_error_counts_as_lost_success_and_never_a_full_ppc_success():
    old = {'tasks': {arm: {str(i): {'status': 'graded', 'resolved': i < 24} for i in range(50)} for arm in batch.ARMS}}
    report = {'tasks': {'harness2': {str(i): {'status': 'error', 'resolved': False,
        'usage': {'tokens': None, 'fresh_model_calls': None}} for i in range(50)}}}
    value = rerun.comparison(report, old)
    assert value['complete'] and value['repair_rate'] == 0
    assert value['errors'] == 50 and value['full_ppc_completed'] == 0
    assert len(value['historical_control']['lost_successes']) == 24
    assert value['tokens'] is None and value['fresh_model_calls'] is None


def test_partial_run_has_counts_but_no_fifty_task_rate():
    old = {'tasks': {arm: {'a': {'status': 'graded', 'resolved': False}} for arm in batch.ARMS}}
    report = {'tasks': {'harness2': {'a': {'status': 'graded', 'resolved': True,
        'result': {'optimization_complete': False, 'adopted_label': 'base1'},
        'usage': {'tokens': 12, 'fresh_model_calls': 2}}}}}
    value = rerun.comparison(report, old)
    assert value['finished'] == 1 and value['repair_rate'] is None
    assert value['tokens'] is None and value['known_tokens_minimum'] == 12
    assert value['resolved'] == 1 and value['full_ppc_completed'] == 0
    assert value['public_fallback_deliveries'] == ['a']


def test_fifty_historical_controls_are_never_rerun(tmp_path, monkeypatch):
    output, events = fixture(tmp_path, monkeypatch)
    report = bridge.read(output / 'report.json')
    report['tasks']['no_harness'] = {f'case-{i:02d}': {'status': 'graded', 'resolved': True,
        'provenance': 'historical', 'usage': {'tokens': 10, 'fresh_model_calls': 0}} for i in range(50)}
    bridge.write(output / 'report.json', report)
    batch.execute(output)
    assert len(events) == 100
    assert [kind for kind, _ in events] == ['model', 'grade'] * 50
    assert all('harness2' in folder for _, folder in events)
