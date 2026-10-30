"""Benchmark admission must preserve task identity, grading evidence and oracle separation."""
import json
import subprocess
from copy import deepcopy
from types import SimpleNamespace

import pytest

from deploy.langfuse.swebench_mini import score_values, validate_items
from evals.swebench_mini import control, load_entry, select, sha, summarize, write


def task(index=0):
    instance_id = 'django__django-' + str(10000 + index)
    return {'instance_id': instance_id, 'repo': 'django/django', 'base_commit': 'a' * 40,
            'problem_statement': 'Public issue', 'patch': 'private-reference', 'test_patch': 'private-tests',
            'version': '3.1', 'FAIL_TO_PASS': json.dumps(['target']), 'PASS_TO_PASS': json.dumps(['regression']),
            'image': 'swebench/sweb.eval.x86_64.' + instance_id.replace('__', '_1776_') + ':latest'}


def grading(resolved=True):
    return {task()['instance_id']: {'resolved': resolved, 'tests_status': {
        'FAIL_TO_PASS': {'success': ['target'] if resolved else [], 'failure': [] if resolved else ['target']},
        'PASS_TO_PASS': {'success': ['regression'], 'failure': []}}}}


def test_selection_is_fixed_before_model_execution_and_normalizes_json_labels():
    rows = [task(index) for index in range(50)]
    canonical = deepcopy(rows)
    canonical[0]['FAIL_TO_PASS'] = ['target']
    assert select(list(reversed(rows)), canonical)['instance_id'] == task()['instance_id']


@pytest.mark.parametrize('field,value', [('base_commit', 'b' * 40), ('patch', 'changed-answer'),
                                       ('test_patch', 'changed-tests'), ('problem_statement', 'changed-issue'),
                                       ('FAIL_TO_PASS', '["different"]')])
def test_task_or_test_drift_is_rejected(field, value):
    rows = [task(index) for index in range(50)]
    canonical = deepcopy(rows)
    canonical[0][field] = value
    with pytest.raises(ValueError, match='drift'):
        select(rows, canonical)


def test_duplicate_subset_and_unknown_selection_are_rejected():
    rows = [task(index) for index in range(50)]
    with pytest.raises(ValueError, match='50 unique'):
        select(rows[:-1] + [rows[0]], rows)
    with pytest.raises(ValueError, match='outside Mini'):
        select(rows, rows, 'other__repo-123')


def test_untrusted_image_is_rejected():
    rows = [task(index) for index in range(50)]
    canonical = deepcopy(rows)
    canonical[0]['image'] = 'unrelated/image:latest'
    with pytest.raises(ValueError, match='official'):
        select(rows, canonical)


@pytest.mark.parametrize('resolved', [False, True])
def test_parser_counts_determine_resolution(resolved):
    result = summarize(grading(resolved), task())
    assert result['resolved'] is resolved
    assert result['FAIL_TO_PASS']['failed'] == (0 if resolved else 1)
    assert result['PASS_TO_PASS']['passed'] == 1


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'overlap', 'infra', 'contradiction'])
def test_missing_or_inconsistent_grading_is_not_counted_as_success(fault):
    report = grading()
    result = report[task()['instance_id']]
    if fault == 'missing':
        result['tests_status']['FAIL_TO_PASS']['success'] = []
    elif fault == 'duplicate':
        result['tests_status']['FAIL_TO_PASS']['success'] *= 2
    elif fault == 'overlap':
        result['tests_status']['FAIL_TO_PASS']['failure'] = ['target']
    elif fault == 'infra':
        result['infra_failure'] = True
    else:
        result['resolved'] = False
    with pytest.raises(ValueError):
        summarize(report, task())


def test_prepared_input_tampering_is_rejected(tmp_path):
    write(tmp_path / 'agent/input.json', {'instance_id': task()['instance_id']})
    write(tmp_path / 'grader/instance.json', task())
    manifest = {'dataset': 'MariusHobbhahn/swe-bench-verified-mini', 'harness_version': '5.0.2',
                'selected_instance_id': task()['instance_id'],
                'files': {name: sha(tmp_path / name) for name in ('agent/input.json', 'grader/instance.json')}}
    write(tmp_path / 'manifest.json', manifest)
    assert load_entry(tmp_path)[1]['patch'] == 'private-reference'
    write(tmp_path / 'agent/input.json', {'patch': 'leaked-oracle'})
    with pytest.raises(ValueError, match='changed'):
        load_entry(tmp_path)


def output():
    return {'fresh_model_calls': 0, 'is_agent_result': False, 'resolved': True,
            'FAIL_TO_PASS': {'passed': 1, 'total': 1}, 'PASS_TO_PASS': {'passed': 1, 'total': 1}}


def test_experiment_receipt_requires_same_dataset_trace_output_and_scores():
    experiment = {'experiment_id': 'experiment', 'trace_id': 'trace'}
    row = {'experimentId': 'experiment', 'traceId': 'trace', 'experimentDatasetId': 'dataset',
           'endTime': 'now', 'output': json.dumps(output()),
           'scores': [{'name': key, 'value': value} for key, value in score_values(output()).items()]}
    assert validate_items([row], experiment, 'dataset', output())['output_matches_local']
    assert validate_items([], experiment, 'dataset', output()) is None
    assert validate_items([row], experiment, 'other-dataset', output()) is None
    row['scores'].pop()
    assert validate_items([row], experiment, 'dataset', output()) is None


def test_live_model_or_agent_results_cannot_be_mislabeled_as_controls():
    value = output()
    value['fresh_model_calls'] = 1
    with pytest.raises(ValueError, match='no-inference'):
        score_values(value)


@pytest.mark.parametrize('failure', ['wrong_commit', 'timeout'])
def test_control_is_restricted_and_cleans_its_container_after_failure(monkeypatch, tmp_path, failure):
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        if 'rev-parse' in args:
            return (('b' if failure == 'wrong_commit' else 'a') * 40).encode()
        return b''

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired('docker exec', 1)

    monkeypatch.setattr('evals.swebench_mini.docker', docker)
    monkeypatch.setattr('evals.swebench_mini.subprocess.run', timed_out)
    error = ValueError if failure == 'wrong_commit' else subprocess.TimeoutExpired
    with pytest.raises(error):
        control(task(), SimpleNamespace(eval_script='trusted-script'), 'unchanged', 'sha256:' + 'a' * 64,
                tmp_path / 'unchanged', 1)
    create = calls[0]
    assert create[create.index('--network') + 1] == 'none'
    assert create[create.index('--cap-drop') + 1] == 'ALL'
    assert '--memory' in create and '--pids-limit' in create and '--cpus' in create
    assert '--volume' not in create and '--mount' not in create
    assert calls[-1][0:2] == ('rm', '--force')
    assert calls[-1][-1] == create[create.index('--name') + 1]
