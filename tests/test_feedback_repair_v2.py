"""Recorded read/edit/retest continuations; no Docker daemon or model is contacted."""
import copy
import json
from pathlib import Path

import pytest

from repairflow import feedback_repair_v2 as feedback
from repairflow.issue_providers import ScriptedProvider

TASK = {'instance_id': 'feedback-v2-example', 'repo': 'local/example',
        'base_commit': 'a' * 40, 'problem_statement': 'Return three and preserve callers.'}


def action(name, **arguments):
    return {'action': name, 'arguments': arguments}


def read(path='code.py'):
    return action('read_symbol', path=path, symbol='f', offset=0)


def patch(old='return 1', new='return 3', revision=0, path='code.py'):
    return action('apply_patch', workspace_revision=revision,
                  edits=[{'file': path, 'old': old, 'new': new}])


class Recorded(ScriptedProvider):
    def __init__(self, path, replies, hook=None):
        path.write_text(json.dumps([row if isinstance(row, str) else json.dumps(row)
                                    for row in replies]), encoding='utf-8')
        super().__init__(path)
        self.messages, self.hook = [], hook

    def chat(self, messages, **kwargs):
        self.messages.append(copy.deepcopy(messages))
        response = super().chat(messages, **kwargs)
        if self.hook:
            self.hook(len(self.calls))
        return response


def prepared(tmp_path, monkeypatch, *, blocked=0, accepted_text='return 3'):
    baseline, candidate, public = [tmp_path / name for name in ('baseline', 'candidate', 'public')]
    for folder in (baseline, candidate, public):
        folder.mkdir()
    for folder in (baseline, candidate):
        (folder / 'code.py').write_text('def f():\n    return 1\n', encoding='utf-8')
        (folder / 'dependency.py').write_text('def f():\n    return 8\n', encoding='utf-8')
    (public / 'test_admission.py').write_text('# trusted developer checks\n', encoding='utf-8')
    calls = []

    def validate(base, source, allowed, output, *args, **kwargs):
        output.mkdir(parents=True, exist_ok=True)
        text = (source / 'code.py').read_text(encoding='utf-8')
        calls.append(text)
        accepted, preserve = accepted_text in text, 'return -1' not in text

        def group(passed):
            return {'tests_run': 1, 'passed': passed, 'successful': passed,
                    'returncode': 0 if passed else 1, 'timed_out': False,
                    'errors': 0, 'failures': 0 if passed else 1,
                    'skipped': 0, 'expected_failures': 0, 'unexpected_successes': 0}

        infrastructure = 'sandbox_runner_start_failed' if len(calls) <= blocked else None
        return {'status': 'blocked' if infrastructure else 'validated' if accepted else 'rejected',
                'accepted': accepted and preserve and not infrastructure,
                'reasons': [] if accepted else ['public_reproduce_failed'],
                'scope_violations': [], 'syntax_errors': [],
                'infrastructure_error': infrastructure,
                'sandbox': {'image_id': 'pinned-image', 'status': infrastructure or 'completed'},
                'independent': {'result': 'PRIVATE_SENTINEL'},
                'public_checks': {'Reproduce': group(accepted), 'Preserve': group(preserve),
                                  'Target': {'secret': 'PRIVATE_SENTINEL'}}}

    monkeypatch.setattr(feedback, 'validate', validate)
    return (baseline, candidate, ['code.py'], public, 'pkg', TASK, tmp_path / 'run'), calls


def model(tmp_path, replies, hook=None):
    return Recorded(tmp_path / 'recorded-responses.json', replies, hook)


def codes(report):
    return [row['error']['code'] for row in report['actions'] if row.get('error')]


def test_reads_failed_patch_relocates_and_retests_successfully(tmp_path, monkeypatch):
    args, checks = prepared(tmp_path, monkeypatch)
    provider = model(tmp_path, [read(), patch(new='return 2'),
        action('search', query='return 2'), read(), patch('return 2', revision=1)])
    report = feedback.run(*args, llm=provider)
    assert report['status'] == 'ready_for_review' and report['accepted']
    assert len(checks) == report['counts']['public_validations'] == 3
    assert report['counts']['applied_patches'] == report['workspace_revision'] == 2
    assert report['counts']['reads'] == 2 and report['counts']['searches'] == 1
    assert report['fresh_model_calls'] == 0 and report['original_inputs_unchanged']
    assert (args[1] / 'code.py').read_text(encoding='utf-8').endswith('return 1\n')
    receipts = [row['result'] for row in report['actions'] if row.get('action') == 'read_symbol']
    assert [row['workspace_revision'] for row in receipts] == [0, 1]
    assert all(row['receipt_id'] and row['complete_symbol'] and row['content_hash'] for row in receipts)
    assert all(row['usage'] == {'prompt_tokens': None, 'completion_tokens': None}
               for row in report['actions'])
    assert 'PRIVATE_SENTINEL' not in json.dumps(provider.messages)
    assert 'public_reproduce_failed' in json.dumps(provider.messages[-1])


def test_twenty_invalid_requests_do_not_trigger_early_repetition_stop(tmp_path, monkeypatch):
    args, checks = prepared(tmp_path, monkeypatch)
    report = feedback.run(*args, llm=model(tmp_path, [action('invalid')] * 20))
    assert report['status'] == 'feedback_round_limit' and not report['accepted']
    assert report['feedback_rounds_attempted'] == report['counts']['requests'] == 20
    assert report['counts']['applied_patches'] == 0 and len(checks) == 1


def test_twentieth_request_can_publish_successful_patch(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path, monkeypatch)
    replies = [read()] + [action('invalid')] * 18 + [patch()]
    report = feedback.run(*args, llm=model(tmp_path, replies))
    assert report['status'] == 'ready_for_review' and report['accepted']
    assert report['feedback_rounds_attempted'] == 20 and report['workspace_revision'] == 1


@pytest.mark.parametrize(('replies', 'error'), [
    ([patch()], 'source_not_read'),
    ([read(), patch(old='return 999')], 'anchor_not_found'),
    ([read(), patch(revision=1)], 'stale_workspace_revision'),
])
def test_unsafe_patch_is_rejected_without_validation(tmp_path, monkeypatch, replies, error):
    args, checks = prepared(tmp_path, monkeypatch)
    report = feedback.run(*args, llm=model(tmp_path, replies + [action('finish')]))
    assert error in codes(report)
    assert report['status'] == 'agent_finished_unresolved' and not report['accepted']
    assert len(checks) == 1 and report['workspace_revision'] == 0


def test_preservation_regression_rolls_back_and_invalidates_receipts(tmp_path, monkeypatch):
    args, checks = prepared(tmp_path, monkeypatch)
    replies = [read(), patch(new='return -1'), patch(revision=2), read(), patch(revision=2)]
    report = feedback.run(*args, llm=model(tmp_path, replies))
    assert report['accepted'] and report['workspace_revision'] == 3
    assert report['counts']['rollbacks'] == 1 and report['counts']['applied_patches'] == 2
    assert 'source_not_read' in codes(report)
    assert checks == ['def f():\n    return 1\n', 'def f():\n    return -1\n',
                      'def f():\n    return 3\n']


def test_read_permission_does_not_grant_edit_permission(tmp_path, monkeypatch):
    args, checks = prepared(tmp_path, monkeypatch)
    replies = [read('dependency.py'), patch('return 8', 'return 9', path='dependency.py'),
               read(), patch()]
    report = feedback.run(*args, readable_files=['code.py', 'dependency.py'], llm=model(tmp_path, replies))
    assert report['accepted'] and report['counts']['applied_patches'] == 1
    assert 'path_not_allowed' in codes(report) and len(checks) == 2
    assert (args[-1] / 'workspace/dependency.py').read_text(encoding='utf-8').endswith('return 8\n')


@pytest.mark.parametrize('reply', ['not json', {'action': 'read_file'},
    {'tool_calls': [{'name': 'read_file', 'arguments': {'path': 'code.py'}}]}])
def test_invalid_response_consumes_one_request(tmp_path, monkeypatch, reply):
    args, checks = prepared(tmp_path, monkeypatch)
    report = feedback.run(*args, llm=model(tmp_path, [reply]), max_feedback_rounds=1)
    assert report['status'] == 'feedback_round_limit'
    assert report['counts']['requests'] == 1 and report['counts']['applied_patches'] == 0
    assert len(codes(report)) == 1 and len(checks) == 1


def test_cancel_received_with_response_prevents_patch_publication(tmp_path, monkeypatch):
    args, checks = prepared(tmp_path, monkeypatch)
    provider = model(tmp_path, [read(), patch()],
                     lambda call: (args[-1] / 'CANCEL').touch() if call == 2 else None)
    report = feedback.run(*args, llm=provider)
    assert report['status'] == 'cancelled' and not report['accepted']
    assert report['counts']['applied_patches'] == report['workspace_revision'] == 0
    assert len(checks) == 1


@pytest.mark.parametrize(('blocked', 'status', 'requests'), [
    (1, 'agent_finished_unresolved', 1), (2, 'validation_blocked', 0)])
def test_environment_retry_preserves_input_and_never_asks_model_to_fix_it(
        tmp_path, monkeypatch, blocked, status, requests):
    args, checks = prepared(tmp_path, monkeypatch, blocked=blocked)
    report = feedback.run(*args, llm=model(tmp_path, [action('finish')]))
    assert report['status'] == status and report['counts']['environment_retries'] == 1
    assert report['counts']['requests'] == requests
    assert len(checks) == 2 and checks[0] == checks[1]
    assert report['workspace_revision'] == 0 and report['original_inputs_unchanged']


def test_already_publicly_acceptable_candidate_needs_no_model_request(tmp_path, monkeypatch):
    args, checks = prepared(tmp_path, monkeypatch, accepted_text='return 1')
    provider = model(tmp_path, [action('finish')])
    report = feedback.run(*args, llm=provider)
    assert report['accepted'] and report['status'] == 'ready_for_review'
    assert report['counts']['requests'] == report['feedback_rounds_attempted'] == len(provider.calls) == 0
    assert len(checks) == 1


def test_file_pages_use_character_offsets_and_never_claim_whole_file(tmp_path):
    source, output = tmp_path / 'source', tmp_path / 'tools'
    source.mkdir()
    output.mkdir()
    text = "def f():\n    return '" + '中文' * 3100 + "'\n"
    (source / 'code.py').write_text(text, encoding='utf-8')
    tools = feedback.FeedbackTools(source, output, ['code.py'], ['code.py'])
    first = tools.dispatch('read_file', {'path': 'code.py'}, 1)
    second = tools.dispatch('read_file', {'path': 'code.py', 'offset': first['next_offset']}, 2)
    assert first['next_offset'] == len(first['content']) == 6000
    assert first['content'] + second['content'] == text
    assert second['next_offset'] is None
    assert not first['complete_file'] and not second['complete_file']
    assert first['receipt_id'] != second['receipt_id']
    assert first['content_hash'] == second['content_hash']
    symbol = tools.dispatch('read_symbol', {'path': 'code.py', 'symbol': 'f'}, 3)
    assert not symbol['complete_symbol'] and symbol['next_offset'] == 6000


def test_second_publication_write_failure_restores_both_files(tmp_path, monkeypatch):
    args, checks = prepared(tmp_path, monkeypatch)
    args = (*args[:2], ['code.py', 'dependency.py'], *args[3:])
    original_write = Path.write_bytes
    failed, saw_first_write = False, False

    def fail_second_write(path, content):
        nonlocal failed, saw_first_write
        if path == args[-1] / 'workspace/dependency.py' and not failed:
            failed = True
            saw_first_write = 'return 3' in (path.parent / 'code.py').read_text(encoding='utf-8')
            raise OSError('simulated second publication failure')
        return original_write(path, content)

    monkeypatch.setattr(Path, 'write_bytes', fail_second_write)
    edits = [patch()['arguments']['edits'][0],
             patch('return 8', 'return 9', path='dependency.py')['arguments']['edits'][0]]
    report = feedback.run(*args, llm=model(tmp_path, [read(), read('dependency.py'),
        action('apply_patch', workspace_revision=0, edits=edits)]))
    assert failed and saw_first_write and report['status'] == 'controller_failed'
    assert report['workspace_revision'] == report['counts']['applied_patches'] == 0
    assert len(checks) == 1 and report['original_inputs_unchanged']
    for name in ('code.py', 'dependency.py'):
        assert (args[-1] / 'workspace' / name).read_bytes() == (args[1] / name).read_bytes()


def test_syntax_rejection_never_publishes_or_validates_candidate(tmp_path, monkeypatch):
    args, checks = prepared(tmp_path, monkeypatch)
    report = feedback.run(*args, llm=model(tmp_path, [read(), patch(new='return ('), action('finish')]))
    assert 'syntax_error' in codes(report) and report['status'] == 'agent_finished_unresolved'
    assert report['workspace_revision'] == report['counts']['applied_patches'] == 0
    assert len(checks) == 1
    assert (args[-1] / 'workspace/code.py').read_bytes() == (args[1] / 'code.py').read_bytes()


def test_preexisting_preservation_failure_does_not_rollback_improvement(tmp_path, monkeypatch):
    args, checks = prepared(tmp_path, monkeypatch)
    for source in args[:2]:
        (source / 'code.py').write_text('def f():\n    return -1\n', encoding='utf-8')
    report = feedback.run(*args, llm=model(tmp_path, [read(), patch('return -1', 'return 2'),
        action('finish')]))
    assert report['status'] == 'agent_finished_unresolved'
    assert report['counts']['rollbacks'] == 0 and report['counts']['applied_patches'] == 1
    assert report['workspace_revision'] == 1 and len(checks) == 2
    assert (args[-1] / 'workspace/code.py').read_text(encoding='utf-8').endswith('return 2\n')


def test_search_and_explicit_reads_respect_separate_read_allowlist(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path, monkeypatch)
    (args[1] / 'dependency.py').write_text("PRIVATE_IDENTIFIER = 'SENSITIVE_DEPENDENCY_PAYLOAD'\n", encoding='utf-8')
    replies = [action('search', query='PRIVATE_IDENTIFIER', path_glob='*.py'),
               action('read_file', path='dependency.py'), action('finish')]
    provider = model(tmp_path, replies)
    report = feedback.run(*args, readable_files=['code.py'], llm=provider)
    assert report['actions'][0]['result']['matches'] == []
    assert 'path_not_allowed' in codes(report)
    assert 'SENSITIVE_DEPENDENCY_PAYLOAD' not in json.dumps(provider.messages)
    assert report['counts']['reads'] == 0 and report['workspace_revision'] == 0


def test_deadline_expired_during_validation_is_reported_as_task_timeout(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path, monkeypatch)
    original_validate = feedback.validate
    clock, validations = [100.0], []
    monkeypatch.setattr(feedback.time, 'monotonic', lambda: clock[0])

    def expire_after_patch(*values, **kwargs):
        result = original_validate(*values, **kwargs)
        validations.append(result)
        if len(validations) == 2:
            clock[0] = 102.0
            result.update(status='blocked', accepted=False,
                          infrastructure_error='validation_deadline_exceeded')
        return result

    monkeypatch.setattr(feedback, 'validate', expire_after_patch)
    report = feedback.run(*args, timeout=1, llm=model(tmp_path, [read(), patch()]))
    assert report['status'] == 'task_timeout' and not report['accepted']
    assert report['counts']['public_validations'] == 2
    assert report['counts']['applied_patches'] == 1


def test_final_public_feedback_reads_logs_from_actual_validation_folder(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path, monkeypatch)
    original_validate = feedback.validate

    def with_public_log(*values, **kwargs):
        result = original_validate(*values, **kwargs)
        logs = values[3] / 'public-logs'
        logs.mkdir()
        (logs / 'Reproduce.stderr.txt').write_text('PUBLIC_FAILURE_DETAIL', encoding='utf-8')
        return result

    monkeypatch.setattr(feedback, 'validate', with_public_log)
    report = feedback.run(*args, llm=model(tmp_path, [action('finish')]))
    assert report['status'] == 'agent_finished_unresolved'
    final_feedback = report['last_public_result']['public_checks']['Reproduce']
    assert final_feedback['stderr_tail'] == 'PUBLIC_FAILURE_DETAIL'
    assert final_feedback['omitted_characters'] == 0


def test_opt_in_context_contract_runs_relocate_cycle_and_records_schema_and_usage(tmp_path, monkeypatch):
    args, checks = prepared(tmp_path, monkeypatch)
    provider = model(tmp_path, [read(), patch(new='return 2'),
        action('search', query='return 2'), read(), patch('return 2', revision=1)])
    original_chat, options = provider.chat, []

    def chat(messages, **kwargs):
        options.append(kwargs)
        return original_chat(messages, **kwargs)

    provider.chat = chat
    report = feedback.run(*args, llm=provider, context_contract=True)
    assert report['accepted'] and report['protocol'] == feedback.CONTRACT_PROTOCOL
    assert len(checks) == 3 and report['counts']['requests'] == 5
    assert all(row['response_schema'] == options[0]['response_schema'] and row['max_tokens'] == -1 for row in options)
    protocol = json.loads((args[-1] / 'protocol.json').read_text(encoding='utf-8'))
    assert protocol['context_contract']['schema_id'] == 'feedback-actions-schema-v1'
    assert 'repairflow/feedback_context.py' in protocol['source_sha256']
    assert (args[-1] / 'action-schema.json').is_file()
    for request in sorted((args[-1] / 'requests').iterdir()):
        context = json.loads((request / 'context.json').read_text(encoding='utf-8'))
        assert context['native_usage'] == {'prompt_tokens': None, 'completion_tokens': None}
        assert context['server_truncation'] == 'not_verified'
        assert context['estimate_after']['response_format_estimate'] > 0
    assert 'PRIVATE_SENTINEL' not in json.dumps(provider.messages)
    assert 'Action JSON Schema' in provider.messages[0][0]['content']


def test_contract_schema_rejection_consumes_a_request_without_dispatch(tmp_path, monkeypatch):
    args, checks = prepared(tmp_path, monkeypatch)
    provider = model(tmp_path, [action('read_file', path='code.py', offset=True),
        read(), patch()])
    report = feedback.run(*args, llm=provider, context_contract=True)
    assert report['accepted'] and report['counts']['requests'] == 3
    assert report['counts']['reads'] == report['counts']['applied_patches'] == 1
    assert len(checks) == 2
    assert report['actions'][0]['error']['field'] == '$.arguments.offset'
    assert '$.arguments.offset' in json.dumps(provider.messages[1])


def test_default_protocol_does_not_send_schema_or_write_context_manifests(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path, monkeypatch)
    provider = model(tmp_path, [action('finish')])
    original_chat, options = provider.chat, []

    def chat(messages, **kwargs):
        options.append(kwargs)
        return original_chat(messages, **kwargs)

    provider.chat = chat
    report = feedback.run(*args, llm=provider)
    assert report['protocol'] == feedback.PROTOCOL
    assert options == [{'tools': []}]
    assert not list(args[-1].rglob('context.json'))
    assert not (args[-1] / 'action-schema.json').exists()


def test_over_target_protected_context_is_sent_intact_without_token_stop(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path, monkeypatch)
    provider = model(tmp_path, [read(), patch()])
    report = feedback.run(*args, llm=provider, context_contract=True, context_target_tokens=1)
    assert report['accepted'] and report['counts']['requests'] == 2
    context = json.loads((args[-1] / 'requests/002/context.json').read_text(encoding='utf-8'))
    assert context['status'] == 'protected_over_target'
    assert context['source_fragments']['selected_count'] == 1
    assert 'return 1' in provider.messages[-1][1]['content']


def test_optional_events_record_actions_and_only_public_validation_groups(tmp_path, monkeypatch):
    from evals.runtime import Events

    args, _ = prepared(tmp_path, monkeypatch)
    path = tmp_path / 'trace.jsonl'
    report = feedback.run(*args, llm=model(tmp_path, [read(), patch()]), context_contract=True,
                          events=Events(path, 'recorded-feedback-events'))
    assert report['accepted']
    records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    checks = [row for row in records if row['event'] == 'public_checks_finished']
    assert len(checks) == 2 and checks[-1]['passed']
    assert all(set(row['groups']) == {'Reproduce', 'Preserve'} for row in checks)
    assert 'PRIVATE_SENTINEL' not in path.read_text(encoding='utf-8')
    assert [row['action'] for row in records if row['event'] == 'agent_action'] == ['read_symbol', 'apply_patch']


def test_event_sink_failure_does_not_change_patch_acceptance(tmp_path, monkeypatch):
    args, _ = prepared(tmp_path, monkeypatch)

    class BrokenSink:
        def emit(self, *args, **kwargs):
            raise RuntimeError('Recorder unavailable')

    report = feedback.run(*args, llm=model(tmp_path, [read(), patch()]), events=BrokenSink())
    assert report['accepted'] and set(report['event_errors']) == {'RuntimeError'}
