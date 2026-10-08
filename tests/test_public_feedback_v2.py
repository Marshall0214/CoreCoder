import json
from types import SimpleNamespace

import pytest

from docs.experiments import public_feedback_cases_v1 as examples
from docs.experiments import public_feedback_report_v2 as reporting
from docs.experiments import public_feedback_v2 as policy
from evals.runner import digest, snapshot


def outcome(passed=True, **fields):
    return dict(passed=passed, timed_out=False, tests_run=1, failures=int(not passed), errors=0, **fields)


def test_certificate_rejects_harness_error_zero_tests_reference_failure_and_preservation_regression():
    valid = {'before': {'Reproduce': outcome(False), 'Preserve': outcome()},
             'after': {'Reproduce': outcome(), 'Preserve': outcome()}}
    assert policy.certified(valid)
    for label, group, changes in [('before', 'Reproduce', {'tests_run': 0}),
                                  ('before', 'Reproduce', {'timed_out': True}),
                                  ('before', 'Preserve', {'passed': False}),
                                  ('after', 'Reproduce', {'passed': False})]:
        altered = json.loads(json.dumps(valid))
        altered[label][group].update(changes)
        assert not policy.certified(altered)


def test_all_public_cases_are_compilable_and_have_no_private_imports():
    assert len(examples.CASES) == 30
    for task in examples.CASES:
        source = examples.code(task)
        compile(source, task, 'exec')
        assert 'class Reproduce' in source and 'class Preserve' in source
        assert 'docs.experiments' not in source and 'evals.' not in source
        assert 'admission.json' not in source


def test_diagnostic_retains_public_failure_but_redacts_candidate_and_harness_paths(tmp_path):
    source, harness = tmp_path / 'source', tmp_path / 'checks'
    (tmp_path / 'Reproduce.stderr.txt').write_text(str(source) + '\n' + str(harness) + '\nAssertionError: expected 7')
    result = policy.diagnostic({'Reproduce': outcome(False), 'Preserve': outcome()}, tmp_path, source, harness)
    assert 'expected 7' in result and str(source) not in result and str(harness) not in result


@pytest.mark.parametrize('mode', ['accepted', 'failed_checks', 'invalid_patch', 'no_failure', 'initial_invalid'])
def test_bounded_correction_shares_initial_and_retains_only_public_valid_patch(tmp_path, monkeypatch, mode):
    workspace, harness = tmp_path / 'workspace', tmp_path / 'checks'
    workspace.mkdir()
    harness.mkdir()
    (workspace / 'code.py').write_text('original')
    (harness / 'test_admission.py').write_text('public check')
    job = {'workspace': str(workspace), 'harness': str(harness), 'harness_hash': digest(snapshot(harness)),
           'allowed_files': ['code.py'], 'evidence': [], 'description': 'public requirement',
           'package': 'example', 'source_root': '.'}
    path = tmp_path / 'job.json'
    path.write_text(json.dumps(job))

    class LLM:
        def __init__(self, *args):
            self.calls = 0

        def metrics(self):
            return {'llm_calls': self.calls, 'budget_accounted_tokens': self.calls * 100}

    calls = []

    def request(llm, source, job, evidence, root, stage, feedback=None):
        calls.append((llm, stage, feedback))
        llm.calls += 1
        if stage == 'initial':
            (source / 'code.py').write_text('first')
            return {'status': 'invalid_patch' if mode == 'initial_invalid' else 'completed'}
        assert feedback['test_code'] == 'public check'
        assert 'private' not in feedback['test_code']
        (source / 'code.py').write_text('corrected')
        return {'status': 'invalid_patch' if mode == 'invalid_patch' else 'completed'}

    def checked(source, harness, package, source_root, logs):
        passed = mode == 'no_failure' or (logs.name == 'public-corrected' and mode == 'accepted')
        return {'Reproduce': outcome(passed), 'Preserve': outcome()}

    monkeypatch.setattr(policy.repair, 'check_identity', lambda config: None)
    monkeypatch.setattr(policy, 'Provider', lambda *args: SimpleNamespace(calls=[], client=SimpleNamespace(close=lambda: None)))
    monkeypatch.setattr(policy, 'CheckedBudgetLLM', LLM)
    monkeypatch.setattr(policy, 'request', request)
    monkeypatch.setattr(policy, 'public_check', checked)
    monkeypatch.setattr(policy, 'refresh_seeds', lambda *args: {'evidence': []})
    monkeypatch.setattr(policy, 'diagnostic', lambda *args: 'public assertion')
    policy.worker(path)
    result = json.loads((tmp_path / 'worker-result.json').read_text())
    assert (tmp_path / 'initial-workspace' / 'code.py').read_text() == 'first'
    expected_calls = 1 if mode in ('no_failure', 'initial_invalid') else 2
    assert len(calls) == result['metrics']['llm_calls'] == expected_calls
    assert result['initial_metrics']['llm_calls'] == 1
    assert all(call[0] is calls[0][0] for call in calls)
    assert (workspace / 'code.py').read_text() == ('corrected' if mode == 'accepted' else 'first')


def test_invalid_structured_patch_cannot_partially_mutate_source(tmp_path, monkeypatch):
    source = tmp_path / 'workspace'
    source.mkdir()
    (source / 'code.py').write_text('def value():\n    return 1\n')
    monkeypatch.setattr(policy.repair, 'validate_evidence', lambda *args: None)

    def bad_patch(response, staging, allowed, evidence):
        (staging / 'code.py').write_text('corrupted')
        raise ValueError('second replacement is invalid')

    monkeypatch.setattr(policy, 'apply_symbol_patch', bad_patch)
    llm = SimpleNamespace(chat=lambda *args, **kwargs: SimpleNamespace(content='{}', tool_calls=[]))
    result = policy.request(llm, source, {'description': 'public', 'allowed_files': ['code.py']}, [], tmp_path, 'initial')
    assert result['status'] == 'invalid_patch'
    assert (source / 'code.py').read_text() == 'def value():\n    return 1\n'


def test_first_prompt_matches_single_baseline_and_contains_no_public_checks(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    monkeypatch.setattr(policy.repair, 'validate_evidence', lambda *args: None)
    monkeypatch.setattr(policy, 'apply_symbol_patch', lambda *args: [])
    received = []

    def chat(messages, **kwargs):
        received.append(messages)
        return SimpleNamespace(content='{}', tool_calls=[])

    job = {'description': 'public requirement', 'allowed_files': ['code.py']}
    evidence = [{'content': 'raw', 'reason': 'explicit_function', 'rank': 1}]
    policy.request(SimpleNamespace(chat=chat), source, job, evidence, tmp_path, 'initial')
    assert received[0][0]['content'] == policy.repair.patcher.SYMBOL_SYSTEM
    assert json.loads(received[0][1]['content']) == dict(job, fragments=evidence)
    assert 'test_code' not in received[0][1]['content']


def test_paired_report_does_not_double_count_shared_initial_usage():
    rows = []
    for i in range(30):
        for strategy in ('single', 'public-feedback'):
            rows.append({'task_id': str(i), 'policy': strategy, 'accepted': True,
                         'worker': {'status': 'completed', 'metrics': {
                             'llm_calls': 1 if strategy == 'single' else 2,
                             'budget_accounted_tokens': 100 if strategy == 'single' else 200}},
                         'verification': {'passed': True, 'groups': {'Target': outcome(), 'Controls': outcome()}}})
    result = reporting.comparison(rows)
    assert result['actual_model_calls'] == 60  # 30 initial + 30 corrections; not 90
    assert result['actual_tokens'] == 6000
    assert not result['gained'] and not result['lost']
    with pytest.raises(ValueError, match='Duplicate'):
        reporting.comparison(rows + [rows[0]])
    with pytest.raises(ValueError, match='complete'):
        reporting.comparison(rows[:-1])
