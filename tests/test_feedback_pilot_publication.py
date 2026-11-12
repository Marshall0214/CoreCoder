"""Pilot publication verifies native usage without re-running any model or tests."""
import json
from copy import deepcopy

import pytest

from deploy.langfuse import feedback_pilot as publisher
from integrations.harness2 import read, sha, write


def accounting(calls=1, *, unknown=False):
    return {'llm_calls': calls, 'prompt_tokens': None if unknown else 10 * calls,
            'completion_tokens': None if unknown else 3 * calls,
            'known_prompt_tokens': 0 if unknown else 10 * calls,
            'known_completion_tokens': 0 if unknown else 3 * calls,
            'missing_usage_calls': calls if unknown else 0}


def batch_fixture(tmp_path, count=5, *, unknown=False):
    batch = tmp_path / 'pilot'
    batch.mkdir()
    ids = [f'case-{index}' for index in range(count)]
    write(batch / 'protocol.json', {'name': publisher.PROTOCOL, 'task_ids': ids})
    states = {}
    for key in ids:
        folder = batch / 'tasks' / key
        write(folder / 'public.json', {'instance_id': key, 'repo': 'fixture/repo', 'base_commit': 'pin',
                                      'problem_statement': 'PRIVATE PROBLEM STATEMENT'})
        metric = accounting(unknown=unknown)
        states[key] = {'status': 'graded', 'resolved': True, 'initial_status': 'ended',
            'feedback_status': 'ready_for_review', 'public_accepted': True,
            'fresh_model_calls': 1, 'metrics': metric, 'final_candidate_hash': 'candidate-hash',
            'phases': [{'phase': 'initial', 'trace_id': key + '-initial',
                        'fresh_model_calls': 1, 'metrics': metric},
                       {'phase': 'feedback', 'trace_id': None,
                        'fresh_model_calls': 0, 'metrics': accounting(0)}],
            'private_source': 'PRIVATE SOURCE CODE'}
        write(folder / 'feedback/report.json', {'final_candidate_hash': 'candidate-hash',
                                                'private_trace': 'PRIVATE TRACE'})
        group = {'passed': True, 'tests_run': 2, 'failures': 0, 'errors': 0,
                 'stderr': 'PRIVATE TARGET BODY', 'test_cases': ['PRIVATE TEST NAME']}
        write(folder / 'grading/report.json', {'passed': True, 'resolved': True,
            'scope_violations': [], 'groups': {'Target': group, 'Controls': group},
            'command': 'PRIVATE COMMAND', 'raw_report': 'PRIVATE GRADING'})
    write(batch / 'report.json', {'protocol_sha256': sha(batch / 'protocol.json'), 'tasks': states,
                                'summary': {'private_summary': 'PRIVATE SUMMARY'}})
    return batch


def native(trace, *, unknown=False):
    common = {'traceId': trace, 'endTime': '2026-11-09T10:00:00Z'}
    return [{**common, 'id': trace + '-root', 'name': 'issue-repair', 'type': 'AGENT'},
            {**common, 'id': trace + '-gen', 'name': 'model-call', 'type': 'GENERATION',
             'usageDetails': {} if unknown else {'input': 10, 'output': 3}}]


class Response:
    def __init__(self, rows):
        self.rows = rows

    def raise_for_status(self):
        pass

    def json(self):
        return {'data': deepcopy(self.rows)}


class FakeService:
    def __init__(self, batch, *, unknown=False):
        self.rows = {phase['trace_id']: native(phase['trace_id'], unknown=unknown)
                     for state in read(batch / 'report.json')['tasks'].values()
                     for phase in state['phases'] if phase['trace_id']}
        self.scores = {}
        self.sent = []
        self.shutdowns = self.flushes = 0

    def reader(self, **kwargs):
        assert kwargs['trust_env'] is False
        return self

    def factory(self, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, params):
        collection = self.scores if url.endswith('/scores') else self.rows
        return Response(collection.get(params['traceId'], []))

    def start_observation(self, **kwargs):
        trace = kwargs['trace_context']['trace_id']
        return FakeSpan(self, trace, kwargs)

    def create_score(self, **kwargs):
        self.sent.append(kwargs)
        rows = self.scores.setdefault(kwargs['trace_id'], [])
        rows[:] = [row for row in rows if row['id'] != kwargs['score_id']]
        rows.append({'id': kwargs['score_id'], 'name': kwargs['name'], 'value': kwargs['value']})

    def flush(self):
        self.flushes += 1

    def shutdown(self):
        self.shutdowns += 1


class FakeSpan:
    def __init__(self, service, trace, data):
        self.service, self.trace = service, trace
        self.row = {'id': 'obs-' + str(len(service.sent)), 'traceId': trace,
                    'name': data['name'], 'type': data['as_type'].upper(),
                    'output': deepcopy(data.get('output'))}
        service.sent.append(deepcopy(data))

    def start_observation(self, **kwargs):
        return FakeSpan(self.service, self.trace, kwargs)

    def end(self):
        self.row['endTime'] = '2026-11-09T11:00:00Z'
        self.service.rows.setdefault(self.trace, []).append(self.row)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(publisher, 'configuration', lambda: {
        'base_url': 'http://127.0.0.1:3300', 'public_key': 'local-public', 'secret_key': 'local-secret'})


def test_five_tasks_publish_verified_summaries_scores_and_native_usage(tmp_path, configured):
    batch = batch_fixture(tmp_path)
    service = FakeService(batch)
    source_hash = sha(batch / 'report.json')
    receipt = publisher.publish(batch, factory=service.factory, reader_factory=service.reader)
    assert receipt['status'] == 'passed'
    assert receipt['publication_model_calls'] == 0
    assert receipt['verified_task_summaries'] == receipt['verified_inference_traces'] == 5
    assert len(receipt['summary_trace_ids']) == 5
    assert service.shutdowns == service.flushes == 1
    assert sha(batch / 'report.json') == source_hash
    assert read(batch / 'langfuse.json') == receipt
    assert all(row['generation_count'] == 1 and row['prompt_tokens'] == 10
               for row in receipt['inference_receipts'])
    assert 'PRIVATE' not in json.dumps(service.sent)
    for trace in [key + '-initial' for key in read(batch / 'protocol.json')['task_ids']]:
        assert {row['name']: row['value'] for row in service.scores[trace]} == {
            'independent_grading_available': 1, 'local_target_controls_passed': 1}
    # Re-publication reuses deterministic summaries and score IDs.
    before = sum(len(rows) for rows in service.rows.values())
    assert publisher.publish(batch, factory=service.factory, reader_factory=service.reader)['status'] == 'passed'
    assert sum(len(rows) for rows in service.rows.values()) == before


def test_missing_usage_stays_null_and_lower_bound_is_explicit(tmp_path, configured):
    batch = batch_fixture(tmp_path, unknown=True)
    service = FakeService(batch, unknown=True)
    receipt = publisher.publish(batch, factory=service.factory, reader_factory=service.reader)
    assert receipt['status'] == 'passed'
    assert all(row['prompt_tokens'] is None and row['completion_tokens'] is None
               and row['known_prompt_tokens'] == 0 and row['missing_usage_calls'] == 1
               for row in receipt['inference_receipts'])
    # Server default zeros cannot turn absent provider usage into measured zero.
    service.rows['case-0-initial'][1]['usageDetails'] = {'input': 0, 'output': 0}
    assert publisher.publish(batch, factory=service.factory, reader_factory=service.reader)['status'] == 'failed'


def test_unknown_usage_cannot_be_recorded_as_complete_zero_totals():
    value = accounting(unknown=True)
    value.update(prompt_tokens=0, completion_tokens=0)
    with pytest.raises(ValueError, match='Incomplete provider usage'):
        publisher.metrics(value, 1)


def test_true_grade_requires_passing_independent_target_and_controls(tmp_path):
    batch = batch_fixture(tmp_path)
    path = batch / 'tasks/case-0/grading/report.json'
    grade = read(path)
    grade['groups']['Target']['passed'] = False
    write(path, grade)
    with pytest.raises(ValueError, match='passing independent checks'):
        publisher.collect(batch)


@pytest.mark.parametrize('mutation', ['tokens', 'call_count', 'unfinished', 'duplicate', 'wrong_trace'])
def test_native_receipt_mismatch_never_publishes_success(tmp_path, configured, mutation):
    batch = batch_fixture(tmp_path)
    service = FakeService(batch)
    rows = service.rows['case-0-initial']
    if mutation == 'tokens':
        rows[1]['usageDetails']['input'] = 11
    elif mutation == 'call_count':
        rows.pop()
    elif mutation == 'unfinished':
        rows[0]['endTime'] = None
    elif mutation == 'duplicate':
        rows.append(deepcopy(rows[0]))
    else:
        rows[0]['traceId'] = 'another-trace'
    receipt = publisher.publish(batch, factory=service.factory, reader_factory=service.reader, timeout=0)
    assert receipt['status'] == 'failed' and receipt['error_type'] == 'ValueError'
    assert service.sent == []


@pytest.mark.parametrize('artifact', ['protocol', 'grade', 'candidate', 'phase'])
def test_local_evidence_mismatch_rejected_before_network(tmp_path, configured, artifact):
    batch = batch_fixture(tmp_path)
    if artifact == 'protocol':
        write(batch / 'protocol.json', {'name': publisher.PROTOCOL, 'task_ids': []})
    elif artifact == 'grade':
        path = batch / 'tasks/case-0/grading/report.json'
        grade = read(path)
        grade['resolved'] = False
        write(path, grade)
    elif artifact == 'candidate':
        write(batch / 'tasks/case-0/feedback/report.json', {'final_candidate_hash': 'changed'})
    else:
        report = read(batch / 'report.json')
        report['tasks']['case-0']['phases'][0]['metrics']['known_prompt_tokens'] = 99
        write(batch / 'report.json', report)
    def forbidden(**kwargs):
        raise AssertionError('No service call should occur')
    receipt = publisher.publish(batch, factory=forbidden, reader_factory=forbidden)
    assert receipt['status'] == 'failed' and receipt['error_type'] == 'ValueError'
    assert receipt['publication_model_calls'] == 0


def test_summary_and_score_readback_are_required(tmp_path, configured):
    batch = batch_fixture(tmp_path)
    service = FakeService(batch)
    service.create_score = lambda **kwargs: None
    receipt = publisher.publish(batch, factory=service.factory, reader_factory=service.reader, timeout=0)
    assert receipt['status'] == 'failed' and receipt['error_type'] == 'TimeoutError'


def test_no_assumption_of_fifty_tasks_and_infra_is_not_a_failed_repair(tmp_path, configured):
    batch = batch_fixture(tmp_path, count=2)
    report = read(batch / 'report.json')
    state = report['tasks']['case-1']
    state.update(status='infra_error')
    state.pop('resolved')
    write(batch / 'report.json', report)
    service = FakeService(batch)
    receipt = publisher.publish(batch, factory=service.factory, reader_factory=service.reader)
    assert receipt['status'] == 'passed' and receipt['verified_task_summaries'] == 2
    summary = [row['output'] for row in service.sent if row.get('name') == publisher.SUMMARY]
    assert 'resolved' not in next(row for row in summary if row['instance_id'] == 'case-1')
    assert not service.scores.get('case-1-initial')
