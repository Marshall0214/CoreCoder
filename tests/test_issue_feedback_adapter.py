"""Shared Issue feedback execution; recorded responses and fake public checks only."""
import copy
import json
import sys

import pytest

from repairflow import feedback_repair_v2, issue_providers, issue_repair
from repairflow.bundles import read, tree_hash, write
from repairflow.issue_registry import load, register
from sandbox import runner
from tests.issue_service_fixture import admitted
from tests.test_github_issue import outcome

POLICY = {'backend': 'docker', 'image_id': 'sha256:' + '2' * 64, 'network': 'none'}
PROFILE = {'exploration_requests': 20, 'feedback_requests': 20, 'exploration_seconds': 1200,
           'feedback_seconds': 1200, 'context_target_tokens': 12000}
SOURCE = 'src/pkg/__init__.py'
DEPENDENCY = 'src/pkg/dependency.py'


def action(name, **arguments):
    return json.dumps({'action': name, 'arguments': arguments})


def correction_rows():
    return [
        action('finish'),
        action('read_symbol', path=SOURCE, symbol='f'),
        action('apply_patch', workspace_revision=0,
               edits=[{'file': SOURCE, 'old': 'return x + 1', 'new': 'return x + 0'}]),
        action('read_symbol', path=DEPENDENCY, symbol='STEP'),
        action('read_symbol', path=SOURCE, symbol='f'),
        action('apply_patch', workspace_revision=1, edits=[
            {'file': SOURCE, 'old': 'return x + 0', 'new': 'from .dependency import STEP\n    return x + STEP'}]),
    ]


def state(source):
    code = (source / SOURCE).read_text(encoding='utf-8')
    reproduce = 'return x + 2' in code or ('from .dependency import STEP' in code and 'return x + STEP' in code)
    preserve = 'def g(x):\n    return x\n' in code
    return reproduce, preserve


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setenv('CORECODER_LANGFUSE_ENABLED', '0')
    monkeypatch.setattr(runner, 'preflight', lambda image=None: dict(POLICY))

    def run(source, harness, package, source_root, logs, name, *args):
        assert package == 'pkg' and source_root == 'src'
        passed = state(source)[0 if name == 'Reproduce' else 1]
        logs.mkdir(exist_ok=True)
        (logs / (name + '.stderr.txt')).write_text('' if passed else 'AssertionError: public reproduction failed', encoding='utf-8')
        return outcome(not passed, timed_out=False)

    monkeypatch.setattr(runner, 'run', run)
    validation_calls, messages = [], []

    def validate(baseline, source, allowed, output, public, package, source_root='.', **kwargs):
        assert package == 'pkg' and source_root == 'src'
        assert allowed == [SOURCE]
        output.mkdir(parents=True, exist_ok=False)
        reproduce, preserve = state(source)
        validation_calls.append({'source': (source / SOURCE).read_text(encoding='utf-8'),
                                 'owner': kwargs.get('owner'), 'outcome': (reproduce, preserve),
                                 'sandbox_image_id': kwargs.get('sandbox_image_id')})
        logs = output / 'public-logs'
        logs.mkdir()
        for name, passed in [('Reproduce', reproduce), ('Preserve', preserve)]:
            (logs / (name + '.stderr.txt')).write_text('' if passed else 'PUBLIC_FAILURE_DETAIL', encoding='utf-8')

        def group(passed):
            return dict(outcome(not passed, timed_out=False), passed=passed)

        return {'schema': 'patch-validator-v1', 'status': 'validated' if reproduce and preserve else 'rejected',
                'accepted': reproduce and preserve, 'scope_violations': [], 'reasons': [], 'syntax_errors': [],
                'model_calls': 0, 'independent_grading_used': False, 'sandbox': dict(POLICY),
                'public_checks': {'Reproduce': group(reproduce), 'Preserve': group(preserve),
                                  'Target': {'secret': 'PRIVATE_GRADING_SENTINEL'}},
                'independent': {'secret': 'PRIVATE_GRADING_SENTINEL'}}

    monkeypatch.setattr(feedback_repair_v2, 'validate', validate)
    original_chat = issue_providers.ScriptedProvider.chat

    def chat(self, request, **kwargs):
        messages.append(copy.deepcopy(request))
        return original_chat(self, request, **kwargs)

    monkeypatch.setattr(issue_providers.ScriptedProvider, 'chat', chat)
    monkeypatch.setattr(issue_providers.OllamaProvider, 'chat',
                        lambda *args, **kwargs: pytest.fail('Recorded adapter must never perform inference'))
    task = admitted(tmp_path / 'inputs')
    return task, validation_calls, messages


def execute(tmp_path, prepared, rows=None, **kwargs):
    task, calls, messages = prepared
    responses = tmp_path / 'responses.json'
    write(responses, rows if rows is not None else correction_rows())
    report = issue_repair.execute(*task, tmp_path / 'run', mode='scripted', responses=responses,
                                  workflow='feedback-actions-v2', execution_profile=PROFILE, **kwargs)
    return report, calls, messages


def test_shared_adapter_records_failed_patch_and_public_success_without_independent_acceptance(tmp_path, prepared):
    task, _, _ = prepared
    original = tree_hash(task[0]), tree_hash(task[1].parent)
    report, calls, messages = execute(tmp_path, prepared)
    assert report['status'] == 'public_checks_passed' and report['public_checks_passed']
    assert report['delivery_status'] == 'ready_for_review' and report['requires_review']
    assert report['accepted'] is False and report['independent_verification'] == {'available': False, 'passed': None}
    assert report['fresh_model_calls'] == 0 and not report['fresh_inference']
    assert report['scripted_calls'] == 6 and report['metrics']['prompt_tokens'] is None
    assert report['metrics']['completion_tokens'] is None and report['metrics']['usage_status'] == 'not_applicable'
    assert [row['outcome'] for row in calls] == [(False, True), (False, True), (True, True)]
    assert len(messages) == 6 and 'PRIVATE_GRADING_SENTINEL' not in json.dumps(messages)
    assert original == (tree_hash(task[0]), tree_hash(task[1].parent)) and report['original_unchanged']
    feedback = read(tmp_path / 'run/feedback/report.json')
    assert feedback['counts']['requests'] == 5 and feedback['counts']['reads'] == 3
    assert feedback['counts']['applied_patches'] == 2 and feedback['counts']['public_validations'] == 3
    assert '+    return x + STEP' in (tmp_path / 'run/patch.diff').read_text(encoding='utf-8')
    assert not (tmp_path / 'run/grading').exists()
    for name in ('report.json', 'patch.diff', 'actions.json', 'trace.jsonl', 'provenance.json',
                 'observability.json', 'context-selection.json'):
        assert (tmp_path / 'run' / name).is_file(), name


def test_shared_adapter_keeps_failed_candidate_report_at_feedback_request_limit(tmp_path, prepared):
    report, calls, _ = execute(tmp_path, prepared, [action('finish')] + [action('read_file', path=SOURCE)] * 20)
    assert report['accepted'] is False and not report['public_checks_passed']
    assert report['delivery_status'] != 'ready_for_review' and report['fresh_model_calls'] == 0
    assert report['scripted_calls'] == 21 and len(calls) == 1
    raw = read(tmp_path / 'run/feedback/report.json')
    assert raw['status'] == 'feedback_round_limit' and raw['counts']['requests'] == 20
    assert raw['counts']['applied_patches'] == 0
    assert (tmp_path / 'run/patch.diff').read_text(encoding='utf-8') == ''
    assert (tmp_path / 'run/report.json').is_file()


def test_shared_adapter_uses_the_trusted_service_owner_path_for_every_validation(tmp_path, prepared):
    owner = tmp_path
    report, calls, _ = execute(tmp_path, prepared, sandbox_owner_path=owner)
    assert report['public_checks_passed']
    assert all(row['owner'] == owner.resolve() for row in calls)


def test_shared_adapter_pins_admitted_image_for_every_feedback_validation(tmp_path, prepared, monkeypatch):
    monkeypatch.setenv('CORECODER_SANDBOX_IMAGE', 'ambient-custom:latest')
    report, calls, _ = execute(tmp_path, prepared)
    assert report['public_checks_passed'] and len(calls) == 3
    assert all(row['sandbox_image_id'] == POLICY['image_id'] for row in calls)
    protocol = read(tmp_path / 'run/feedback/protocol.json')
    assert protocol['sandbox_image_id'] == POLICY['image_id']


def test_shared_adapter_rejects_validation_receipt_from_another_image(tmp_path, prepared, monkeypatch):
    original = feedback_repair_v2.validate

    def different_image(*args, **kwargs):
        result = original(*args, **kwargs)
        result['sandbox']['image_id'] = 'sha256:' + 'b' * 64
        result.update(status='validated', accepted=True)
        return result

    monkeypatch.setattr(feedback_repair_v2, 'validate', different_image)
    report, calls, _ = execute(tmp_path, prepared)
    assert len(calls) == 1 and report['status'] == 'controller_failed'
    assert report['public_checks_passed'] is False and report['accepted'] is False
    assert report['delivery_status'] == 'not_delivered'


def test_shared_adapter_refuses_a_sibling_job_owner_before_any_requests(tmp_path, prepared):
    owner = tmp_path / 'other-job'
    owner.mkdir()
    with pytest.raises(ValueError, match='trusted task ancestor'):
        execute(tmp_path, prepared, sandbox_owner_path=owner)
    assert prepared[1] == prepared[2] == []


def test_read_only_dependency_cannot_be_edited_by_the_adapter(tmp_path, prepared):
    replies = [action('finish'), action('read_symbol', path=DEPENDENCY, symbol='STEP'),
               action('apply_patch', workspace_revision=0,
                      edits=[{'file': DEPENDENCY, 'old': 'STEP = 2', 'new': 'STEP = 99'}]), action('finish')]
    report, calls, _ = execute(tmp_path, prepared, replies)
    assert report['accepted'] is False and not report['public_checks_passed'] and len(calls) == 1
    raw = read(tmp_path / 'run/feedback/report.json')
    assert any(row.get('error', {}).get('code') == 'path_not_allowed' for row in raw['actions'])
    assert (tmp_path / 'run/feedback/workspace' / DEPENDENCY).read_text(encoding='utf-8') == 'STEP = 2\n'


def test_registry_pins_optional_feedback_engine_and_profile_without_changing_legacy(tmp_path, prepared):
    task, _, _ = prepared
    response = tmp_path / 'responses.json'
    write(response, correction_rows())
    entry = register(*task, tmp_path / 'catalog/new', responses=response,
                     engine='feedback-actions-v2', execution_profile=PROFILE)
    raw = read(entry / 'entry.json')
    metadata, _ = load(entry)
    assert raw['schema_version'] == 2 and metadata['engine'] == 'feedback-actions-v2'
    assert metadata['execution_profile'] == PROFILE
    legacy = register(*task, tmp_path / 'catalog/legacy')
    assert read(legacy / 'entry.json')['schema_version'] == 1
    assert load(legacy)[0].get('engine', 'symbol-recovery-v1') == 'symbol-recovery-v1'


def test_feedback_registry_rejects_tampered_recorded_responses(tmp_path, prepared):
    task, _, _ = prepared
    response = tmp_path / 'responses.json'
    write(response, correction_rows())
    entry = register(*task, tmp_path / 'catalog/new', responses=response,
                     engine='feedback-actions-v2', execution_profile=PROFILE)
    write(entry / 'responses.json', [action('finish')])
    with pytest.raises(ValueError, match='changed'):
        load(entry)


def test_feedback_adapter_rejects_changed_prepared_source_before_recorded_requests(tmp_path, prepared):
    task, calls, messages = prepared
    (task[0] / 'source' / SOURCE).write_text('def f(x):\n    return 99\n', encoding='utf-8')
    with pytest.raises(ValueError):
        execute(tmp_path, prepared)
    assert not messages and not calls


def test_cli_forwards_the_same_optional_engine_profile_to_the_shared_executor(tmp_path, monkeypatch, capsys):
    from repairflow import __main__ as cli

    profile_file = tmp_path / 'profile.json'
    write(profile_file, PROFILE)
    seen = {}

    def execute(*args, **kwargs):
        seen.update(kwargs)
        return {'status': 'public_checks_passed', 'public_checks_passed': True,
                'accepted': False, 'fresh_model_calls': 0}

    monkeypatch.setattr(issue_repair, 'execute', execute)
    monkeypatch.setattr(sys, 'argv', ['repairflow', 'repair-issue', '--prepared', str(tmp_path / 'prepared'),
        '--config', str(tmp_path / 'config.json'), '--output', str(tmp_path / 'result'),
        '--mode', 'scripted', '--responses', str(tmp_path / 'answers.json'),
        '--workflow', 'feedback-actions-v2', '--execution-profile', str(profile_file)])
    assert cli.main() == 0
    assert seen['workflow'] == 'feedback-actions-v2' and seen['execution_profile'] == PROFILE
    assert json.loads(capsys.readouterr().out)['accepted'] is False


def test_explicit_service_deadline_is_visible_without_reintroducing_a_token_cutoff():
    from repairflow.issue_execution import limits

    settings = limits(PROFILE, service_timeout=240)
    assert settings['requested'] == PROFILE and settings['service_timeout_seconds'] == 240
    assert 0 < settings['total_seconds'] < 240
    assert settings['token_budget'] is settings['max_output_tokens'] is None


@pytest.mark.parametrize('override', [
    {'feedback_requests': False}, {'feedback_requests': 0}, {'exploration_seconds': -1},
    {'unexpected_tool': 'shell'}, {'context_target_tokens': 0},
])
def test_invalid_execution_profile_cannot_register_a_new_strategy(tmp_path, prepared, override):
    task, _, _ = prepared
    profile = {**PROFILE, **override}
    with pytest.raises((ValueError, TypeError)):
        register(*task, tmp_path / 'catalog/rejected', engine='feedback-actions-v2', execution_profile=profile)
    assert not (tmp_path / 'catalog/rejected/entry.json').exists()


def test_feedback_registry_cannot_silently_ignore_a_legacy_observation_policy(tmp_path, prepared):
    task, _, _ = prepared
    with pytest.raises(ValueError, match='fixed context contract'):
        register(*task, tmp_path / 'catalog/rejected', engine='feedback-actions-v2', observation_policy='compact-v1')
    assert not (tmp_path / 'catalog/rejected').exists()
    entry = register(*task, tmp_path / 'catalog/new', engine='feedback-actions-v2')
    metadata = read(entry / 'entry.json')
    metadata['observation_policy'] = 'compact-v1'
    write(entry / 'entry.json', metadata)
    with pytest.raises(ValueError, match='fixed context contract'):
        load(entry)
