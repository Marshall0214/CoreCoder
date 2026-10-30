import json

import pytest

from repairflow.bundles import read, write
from repairflow.github_issue import config
from repairflow.issue_registry import load, register
from repairflow.issue_repair import execute, trusted_task
from tests.issue_service_fixture import admitted, responses
from tests.test_github_issue import URL
from tests.test_issue_repair import task as original_task_fixture


@pytest.fixture
def task(tmp_path, monkeypatch):
    # Install the same explicit fake Docker runner used by existing unit tests.
    original_task_fixture.__wrapped__(tmp_path / 'runner-fixture', monkeypatch)
    return admitted(tmp_path / 'inputs')


def test_read_only_dependency_is_readable_and_target_remains_editable(tmp_path, task):
    prepared, configuration = task
    report = execute(prepared, configuration, tmp_path / 'run', mode='scripted',
                     responses=responses(tmp_path / 'responses.json'), workflow='symbol-recovery-v1')
    assert report['public_checks_passed'] and not report['accepted']
    assert report['actions'][0]['result']['content'] == 'STEP = 2\n'
    assert report['actions'][0]['result']['kind'] == 'assignment'
    payload = json.loads(read(tmp_path / 'run/step-002-messages.json')[1]['content'])
    assert payload['read_only_files'] == ['src/pkg/dependency.py']
    assert payload['allowed_files'] == ['src/pkg/__init__.py']
    assert (tmp_path / 'run/workspace/src/pkg/dependency.py').read_text() == 'STEP = 2\n'


def test_read_receipt_does_not_allow_dependency_edit(tmp_path, task):
    answer = responses(tmp_path / 'responses.json')
    rows = read(answer)
    rows[1] = json.dumps({'edits': [{'file': 'src/pkg/dependency.py', 'old': 'STEP = 2', 'new': 'STEP = 3'}]})
    write(answer, rows)
    report = execute(*task, tmp_path / 'run', mode='scripted', responses=answer, workflow='symbol-recovery-v1')
    assert report['status'] == 'nonretryable_tool_error' and not report['public_checks_passed']
    assert report['actions'][-1]['error']['code'] == 'path_not_allowed'
    assert report['candidate_rolled_back']
    assert (tmp_path / 'run/workspace/src/pkg/dependency.py').read_text() == 'STEP = 2\n'


@pytest.mark.parametrize('scope', ['all', ['../private.py'], ['.env'], ['src/pkg/__init__.py'],
                                 ['src/pkg/dependency.py'] * 2, [None]])
def test_invalid_read_only_configuration_is_rejected(task, scope):
    configuration = task[1]
    data = read(configuration)
    data['read_only_files'] = scope
    write(configuration, data)
    with pytest.raises(ValueError):
        config(configuration, URL)


def test_read_scope_cannot_be_added_to_prepared_metadata(task):
    data = read(task[0] / 'task.json')
    data['read_only_files'] = ['src/pkg/other.py']
    write(task[0] / 'task.json', data)
    with pytest.raises(ValueError, match='read-only scope'):
        trusted_task(*task)


def test_registry_copies_self_contained_inputs_and_refuses_tampering(tmp_path, task):
    destination = tmp_path / 'catalog/sample'
    register(*task, destination, responses=responses(tmp_path / 'responses.json'))
    entry, data = load(destination)
    assert entry['scripted_responses'] and data['read_only_files'] == ['src/pkg/dependency.py']
    assert read(destination / 'config/task.json') == read(task[1])
    with pytest.raises(ValueError, match='new'):
        register(*task, destination)
    (destination / 'prepared/source/src/pkg/dependency.py').write_text('STEP = 99\n')
    with pytest.raises(ValueError, match='changed'):
        load(destination)


def test_registry_validates_scripted_answers_before_copy(tmp_path, task):
    answers = tmp_path / 'bad.json'
    write(answers, ['valid', 7])
    with pytest.raises(ValueError, match='response strings'):
        register(*task, tmp_path / 'catalog/sample', responses=answers)
    assert not (tmp_path / 'catalog/sample').exists()


def test_service_approval_pins_entry_and_never_claims_independent_acceptance(tmp_path, task, monkeypatch):
    pytest.importorskip('langgraph.checkpoint.sqlite')
    from service import issues

    registry = tmp_path / 'catalog'
    root = register(*task, registry / 'sample', responses=responses(tmp_path / 'responses.json'))
    monkeypatch.setenv('CORECODER_ISSUE_TASKS', str(registry))
    job = tmp_path / 'job'
    job.mkdir()
    path = job / 'job.json'
    write(path, {'request': {'suite': 'issues', 'task_id': 'sample', 'mode': 'scripted',
                             'workflow': issues.WORKFLOW, 'search_backend': 'off'}})
    calls = []

    def perform(*args, **kwargs):
        calls.append(kwargs)
        return {'status': 'public_checks_passed', 'public_checks_passed': True, 'accepted': True,
                'original_unchanged': True, 'changed_files': ['src/pkg/__init__.py'], 'delivery_status': 'ready_for_review'}

    monkeypatch.setattr(issues, 'execute', perform)
    assert issues.run(path)['status'] == 'awaiting_approval' and calls == []
    approved = issues.run(path, 'approve')
    assert approved['accepted'] is False and len(calls) == 1
    assert issues.run(path, 'approve') == approved and len(calls) == 1
    assert read(job / 'workflow.json')['stage'] == 'ready_for_review'
    assert read(job / 'workflow.json')['plan']['details']['read_only_files'] == ['src/pkg/dependency.py']
    assert calls[0]['sandbox_owner']
    entry = read(root / 'entry.json')
    entry['model'] = 'different-local-model'
    write(root / 'entry.json', entry)
    with pytest.raises(ValueError, match='entry changed'):
        issues.run(path, 'approve')


def test_new_issue_cleanup_ignores_legacy_host_backend(tmp_path, monkeypatch):
    from sandbox import runner
    from service.manager import Job, TaskManager

    job = Job('sample', {'workflow': 'issue-approval-v1'}, tmp_path)
    monkeypatch.setenv('CORECODER_TEST_BACKEND', 'local')
    calls = []
    monkeypatch.setattr(runner, 'cleanup', lambda root: calls.append(root))
    TaskManager._clean_sandbox(job)
    assert calls == [tmp_path]
