"""Batch denominator, resume isolation, dataset receipts and empty regression labels."""
import io
import json
from copy import deepcopy

import pytest

from deploy.langfuse.swebench_agent import scores
from deploy.langfuse.swebench_batch import verify
from deploy.langfuse.swebench_mini import score_values
from evals.swebench_batch import aggregate, environment, execute
from evals.swebench_images import ImageTransfer, release
from evals.swebench_mini import select, sha, write
from tests.test_swebench_mini import task


def test_empty_regression_group_is_valid_but_empty_target_is_not():
    rows = [task(index) for index in range(50)]
    rows[0]['PASS_TO_PASS'] = '[]'
    assert select(rows, deepcopy(rows))['PASS_TO_PASS'] == '[]'
    rows[0]['FAIL_TO_PASS'] = '[]'
    with pytest.raises(ValueError, match='drift'):
        select(rows, deepcopy(rows))


def test_no_fake_regression_ratio_for_zero_tests():
    output = {'resolved': True, 'FAIL_TO_PASS': {'passed': 1, 'total': 1},
              'PASS_TO_PASS': {'passed': 0, 'total': 0}, 'fresh_model_calls': 0,
              'is_agent_result': False, 'metrics': {}}
    assert 'pass_to_pass' not in scores(output)
    assert 'pass_to_pass' not in score_values(output)
    assert scores(output)['official_resolved'] is True


def test_aggregate_keeps_infrastructure_and_unknown_usage_in_denominator():
    tasks = {'a': {'status': 'graded', 'resolved': True, 'agent_completed': True, 'total_tokens': 12,
                   'fresh_model_calls': 1, 'agent_status': 'agent_finished'},
             'b': {'status': 'infra_error'}, 'c': {'status': 'graded', 'resolved': False,
                                                 'agent_completed': True, 'total_tokens': None}}
    summary = aggregate(['a', 'b', 'c', 'd'], tasks)
    assert summary['resolved_over_scheduled'] == 0.25
    assert summary['resolved_over_graded'] == 0.5
    assert summary['infra_errors'] == 1
    assert summary['usage_unknown_tasks'] == 1
    assert summary['actual_tokens_known_sum'] == 12


def test_agent_environment_excludes_grader_dependencies_and_paid_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'should-not-reach-agent')
    monkeypatch.setenv('PYTHONPATH', 'private-grader-package')
    env = environment('agent', tmp_path)
    assert 'DEEPSEEK_API_KEY' not in env
    assert 'swebench-deps' not in env['PYTHONPATH'] and 'private-grader' not in env['PYTHONPATH']
    assert 'langfuse-deps' in env['PYTHONPATH'] and env['PYTHON_DOTENV_DISABLED'] == '1'
    assert environment('grading', tmp_path)['CORECODER_LANGFUSE_ENABLED'] == '0'


def test_preexisting_image_is_never_deleted(tmp_path, monkeypatch):
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        return json.dumps([{'Id': 'sha256:existing', 'RootFS': {'Layers': ['layer']}}]).encode()

    monkeypatch.setattr('evals.swebench_images.docker', docker)
    receipt = ImageTransfer(tmp_path).load('swebench/sweb.eval.x86_64.django_1776_django-1:latest')
    release(receipt)
    assert receipt['owned'] is False and len(calls) == 1


def test_cleanup_refuses_retagged_image(monkeypatch):
    monkeypatch.setattr('evals.swebench_images.docker', lambda *args, **kwargs: b'[{"Id":"changed"}]')
    with pytest.raises(ValueError, match='refusing cleanup'):
        release({'owned': True, 'tag': 'swebench/task:latest', 'image_id': 'original'})


def test_server_receipt_requires_exact_unique_task_set_and_scores():
    outputs = {'a': {'instance_id': 'a', 'official_grading_available': False}}
    row = {'output': outputs['a'], 'endTime': 'now', 'experimentDatasetId': 'ds', 'experimentId': 'exp',
           'scores': [{'name': 'grading_available', 'value': 0}]}
    assert verify([row], 'ds', 'exp', outputs)
    assert not verify([row, row], 'ds', 'exp', outputs)
    assert not verify([], 'ds', 'exp', outputs)
    row['scores'] = []
    assert not verify([row], 'ds', 'exp', outputs)


def test_serial_resume_does_not_repeat_finished_or_interrupted_inference(tmp_path, monkeypatch):
    ids = [f'task-{index}' for index in range(50)]
    protocol = {'instance_ids': ids, 'model': 'qwen3.5:27b'}
    write(tmp_path / 'protocol.json', protocol)
    tasks = {ids[0]: {'status': 'graded', 'resolved': False}}
    write(tmp_path / 'report.json', {'tasks': tasks, 'protocol_sha256': sha(tmp_path / 'protocol.json')})
    (tmp_path / 'tasks' / ids[1] / 'agent').mkdir(parents=True)
    monkeypatch.setattr('urllib.request.urlopen', lambda *args, **kwargs: io.BytesIO(
        b'{"models":[{"name":"qwen3.5:27b","digest":"same-model"}]}'))
    monkeypatch.setattr('evals.swebench_batch.space', lambda *args: None)
    monkeypatch.setattr('evals.swebench_batch.load_entry', lambda entry: ({}, {'image': 'official-task-image'}))
    monkeypatch.setattr('evals.swebench_batch.ImageTransfer.load', lambda self, tag: {'image_id': 'fixed', 'owned': False})
    monkeypatch.setattr('evals.swebench_batch.release', lambda receipt: None)
    calls = []

    def child(module, args, phase, folder, timeout):
        calls.append((phase, folder.name))
        if phase == 'publish':
            return
        output = args[args.index('--output') + 1]
        if phase == 'controls':
            write(output / 'report.json', {'status': 'passed', 'image_id': 'fixed'})
        elif phase == 'agent':
            output.mkdir()
            (output / 'patch.diff').write_text('')
            write(output / 'report.json', {'status': 'agent_finished', 'fresh_model_calls': 1,
                                          'metrics': {'prompt_tokens': 10, 'completion_tokens': 2}})
        else:
            write(output / 'report.json', {'status': 'completed', 'candidate_sha256': sha(folder / 'agent/patch.diff'),
                                          'candidate': {'resolved': True, 'FAIL_TO_PASS': {}, 'PASS_TO_PASS': {}}})

    monkeypatch.setattr('evals.swebench_batch.child', child)
    result = execute(tmp_path, protocol, resume=True)
    assert result['tasks'][ids[1]]['status'] == 'interrupted_agent'
    assert len([row for row in calls if row[0] == 'agent']) == 48
    assert result['summary']['graded'] == 49
    assert result['status'] == 'completed_with_infra_errors'
