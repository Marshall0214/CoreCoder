"""Feedback budget counts correction requests, independently of old exploration steps."""
import json

import pytest

from repairflow import feedback_repair as feedback
from repairflow.issue_providers import ProviderFailure, UsageResponse

TASK = {'instance_id': 'example', 'repo': 'local/example', 'base_commit': 'a' * 40,
        'problem_statement': 'Return the expected number.'}


class Model:
    def __init__(self, replies, hook=None):
        self.replies, self.hook, self.calls, self.messages = replies, hook, 0, []

    def chat(self, messages, **kwargs):
        self.messages.append(messages)
        self.calls += 1
        if self.hook:
            self.hook()
        value = self.replies[min(self.calls - 1, len(self.replies) - 1)]
        if isinstance(value, Exception):
            raise value
        return UsageResponse(content=json.dumps(value), reported_usage={'prompt_tokens': 10, 'completion_tokens': 5})

    def metrics(self):
        return {'llm_calls': self.calls}


def patch(old, new):
    return {'edits': [{'file': 'code.py', 'old': old, 'new': new}]}


def prepared(tmp_path, monkeypatch, *, accepted_text='return 3', blocked=False):
    base, candidate, public = [tmp_path / name for name in ('baseline', 'candidate', 'public')]
    for path in (base, candidate, public):
        path.mkdir()
    (base / 'code.py').write_text('def f():\n    return 0\n', encoding='utf-8')
    (candidate / 'code.py').write_text('def f():\n    return 1\n', encoding='utf-8')
    (public / 'test_admission.py').write_text('# developer checks\n', encoding='utf-8')

    def validate(baseline, source, allowed, output, *args):
        output.mkdir()
        accepted = accepted_text in (source / 'code.py').read_text(encoding='utf-8')
        return {'status': 'blocked' if blocked else 'validated' if accepted else 'rejected',
                'accepted': accepted and not blocked, 'reasons': ['public_reproduce_failed'] if not accepted else [],
                'sandbox': {'image_id': 'fixed'}, 'independent': {'secret': 'PRIVATE_SENTINEL'},
                'public_checks': {'Reproduce': {'tests_run': 1, 'passed': accepted}}}

    monkeypatch.setattr(feedback, 'validate', validate)
    return (base, candidate, ['code.py'], public, 'pkg', TASK, tmp_path / 'run')


def test_default_twenty_attempts_do_not_stop_on_repeated_bad_patches(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch)
    model = Model([{'edits': []}])
    report = feedback.run(*args, llm=model)
    assert report['max_feedback_rounds'] == report['feedback_rounds_attempted'] == model.calls == 20
    assert report['status'] == 'feedback_round_limit' and not report['accepted']
    assert report['applied_patches'] == 0 and report['fresh_model_calls'] == 0
    assert len(list((args[-1] / 'rounds').glob('*/report.json'))) == 20
    assert all(row['usage'] == {'prompt_tokens': 10, 'completion_tokens': 5} for row in report['rounds'])
    assert 'PRIVATE_SENTINEL' not in json.dumps(model.messages)
    assert report['original_inputs_unchanged']


def test_success_on_twentieth_correction_is_accepted(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch, accepted_text='return 21')
    model = Model([patch(f'return {i}', f'return {i+1}') for i in range(1, 21)])
    report = feedback.run(*args, llm=model)
    assert report['status'] == 'ready_for_review' and report['accepted']
    assert report['feedback_rounds_attempted'] == report['applied_patches'] == 20
    assert 'return 1\n' in (args[1] / 'code.py').read_text(encoding='utf-8')
    assert 'return 21' in (args[-1] / 'workspace/code.py').read_text(encoding='utf-8')


def test_stops_when_public_checks_pass_and_refreshes_source_receipts(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch)
    model = Model([patch('return 1', 'return 2'), patch('return 2', 'return 3')])
    report = feedback.run(*args, llm=model)
    assert report['feedback_rounds_attempted'] == report['applied_patches'] == model.calls == 2
    assert report['accepted'] and report['independent_verification_available'] is False
    second = json.loads(model.messages[1][-1]['content'])
    assert 'return 2' in second['current_fragments'][0]['content']
    assert second['previous_attempts'][0]['public_accepted'] is False


def test_already_acceptable_candidate_needs_no_correction(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch, accepted_text='return 1')
    model = Model([])
    report = feedback.run(*args, llm=model)
    assert report['accepted'] and report['feedback_rounds_attempted'] == model.calls == 0


def test_infrastructure_block_does_not_spend_repair_rounds(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch, blocked=True)
    model = Model([])
    report = feedback.run(*args, llm=model)
    assert report['status'] == 'validation_blocked' and model.calls == 0


def test_cancel_after_response_prevents_applying_it(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch)
    model = Model([patch('return 1', 'return 3')], lambda: (args[-1] / 'CANCEL').touch())
    report = feedback.run(*args, llm=model)
    assert report['status'] == 'cancelled' and report['applied_patches'] == 0
    assert report['rounds'][0]['patch_status'] == 'not_applied'


def test_failed_provider_usage_is_recorded(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch)
    model = Model([ProviderFailure('local_provider_failed', reported_usage={'prompt_tokens': 12})])
    report = feedback.run(*args, llm=model)
    assert report['status'] == 'local_provider_failed' and model.calls == 1
    assert report['rounds'][0]['usage'] == {'prompt_tokens': 12, 'completion_tokens': None}


def test_changed_sandbox_cannot_approve_a_patch(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch)
    original = feedback.validate

    def different(*values):
        result = original(*values)
        if values[3].name != 'validation-000':
            result['sandbox'] = {'image_id': 'changed'}
        return result

    monkeypatch.setattr(feedback, 'validate', different)
    report = feedback.run(*args, llm=Model([patch('return 1', 'return 3')]))
    assert report['status'] == 'controller_failed' and report['accepted'] is False
    assert report['rounds'][0]['status'] == 'controller_failed'


def test_initial_scope_violation_never_reaches_model(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(feedback, 'validate', lambda *values: {
        'status': 'rejected', 'accepted': False, 'scope_violations': ['test_bypass.py']})
    model = Model([])
    report = feedback.run(*args, llm=model)
    assert report['status'] == 'validation_blocked' and model.calls == 0


def test_feedback_is_an_explicit_public_allowlist(tmp_path):
    logs = tmp_path / 'public-logs'
    logs.mkdir()
    (logs / 'Reproduce.stderr.txt').write_text('x' * 12020, encoding='utf-8')
    result = feedback.public_feedback({'status': 'rejected', 'Target': 'PRIVATE_SENTINEL',
        'static': {'candidate_findings': [], 'private': 'PRIVATE_SENTINEL'},
        'public_checks': {'Reproduce': {'passed': False, 'private': 'PRIVATE_SENTINEL'},
                          'Controls': {'private': 'PRIVATE_SENTINEL'}}}, tmp_path)
    assert 'PRIVATE_SENTINEL' not in json.dumps(result)
    assert result['public_checks']['Reproduce']['omitted_characters'] == 20


def test_invalid_limits_and_private_task_fields_are_rejected(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch)
    for limit in (0, -1, True):
        with pytest.raises(ValueError):
            feedback.run(*args, max_feedback_rounds=limit)
    args = (*args[:5], {**TASK, 'Target': 'private'}, args[-1])
    with pytest.raises(ValueError, match='public task'):
        feedback.run(*args)
