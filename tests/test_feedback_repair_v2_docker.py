"""Opt-in Docker read/edit/retest acceptance with recorded responses, never a model.

Run with CORECODER_RUN_DOCKER_TESTS=1 and an existing local sandbox image.
The complete source fixture is three tiny files; no repository is copied.
"""
import copy
import json
import os
import threading
import time
from pathlib import Path

import pytest

from evals.runner import snapshot
from repairflow import feedback_repair_v2 as feedback
from repairflow.issue_providers import ScriptedProvider
from sandbox import runner

pytestmark = pytest.mark.skipif(
    os.environ.get('CORECODER_RUN_DOCKER_TESTS') != '1',
    reason='Opt in with CORECODER_RUN_DOCKER_TESTS=1 and a prebuilt local sandbox image',
)

TASK = {
    'instance_id': 'feedback-v2-recorded-docker', 'repo': 'local/feedback-fixture',
    'base_commit': 'a' * 40,
    'problem_statement': 'total should scale values using the configured factor; zero remains zero.',
}
RULES = 'FACTOR = 2\n'


def action(name, **arguments):
    return {'action': name, 'arguments': arguments}


def read_total():
    return action('read_symbol', path='pkg/calc.py', symbol='total')


def patch(old, new, revision):
    return action('apply_patch', workspace_revision=revision,
                  edits=[{'file': 'pkg/calc.py', 'old': old, 'new': new}])


class Recorded(ScriptedProvider):
    def __init__(self, path, replies, hook=None):
        path.write_text(json.dumps([json.dumps(row) for row in replies]), encoding='utf-8')
        super().__init__(path)
        self.messages, self.hook = [], hook

    def chat(self, messages, **kwargs):
        self.messages.append(copy.deepcopy(messages))
        response = super().chat(messages, **kwargs)
        if self.hook:
            self.hook(len(self.calls))
        return response


def prepared(tmp_path, monkeypatch):
    project = Path(__file__).resolve().parents[1]
    assert tmp_path.resolve().is_relative_to(project), 'Keep test inputs and artifacts in the project on D:'
    monkeypatch.setenv('CORECODER_TEST_BACKEND', 'docker')
    monkeypatch.setenv('CORECODER_LANGFUSE_ENABLED', '0')
    baseline, candidate, public = [tmp_path / name for name in ('baseline', 'candidate', 'public')]
    for root, expression in ((baseline, 'value + FACTOR'), (candidate, 'value - FACTOR')):
        package = root / 'pkg'
        package.mkdir(parents=True)
        (package / '__init__.py').write_text('from .calc import total\n', encoding='utf-8')
        (package / 'rules.py').write_text(RULES, encoding='utf-8')
        (package / 'calc.py').write_text(
            'from .rules import FACTOR\n\ndef total(value):\n    return ' + expression + '\n',
            encoding='utf-8',
        )
    public.mkdir()
    (public / 'test_admission.py').write_text(
        'import unittest\nfrom pkg import total\n\n'
        'class Reproduce(unittest.TestCase):\n'
        '    def test_nonzero_scale(self):\n        self.assertEqual(total(3), 6)\n\n'
        'class Preserve(unittest.TestCase):\n'
        '    def test_zero(self):\n        self.assertEqual(total(0), 0)\n',
        encoding='utf-8',
    )
    return baseline, candidate, ['pkg/calc.py'], public, 'pkg', TASK, tmp_path / 'run'


def validation_reports(output):
    found = []
    for path in output.rglob('report.json'):
        report = json.loads(path.read_text(encoding='utf-8'))
        if report.get('schema') == 'patch-validator-v1':
            found.append((path.parent, report))
    return sorted(found, key=lambda item: item[0].as_posix())


def assert_real_receipts(validations):
    for folder, report in validations:
        assert report['status'] in {'rejected', 'validated'}
        assert report['independent_grading_used'] is False
        assert report['model_calls'] == 0
        assert set(report['public_checks']) == {'Reproduce', 'Preserve'}
        for name, group in report['public_checks'].items():
            assert group['tests_run'] == 1
            assert group['sandbox_status'] == 'completed'
            assert group['runner_transport'] == 'stdin'
            assert group['runner_started'] and group['result_collected']
            assert group['sandbox']['backend'] == 'docker'
            assert group['sandbox']['network'] == 'none'
            receipt = json.loads((folder / 'public-logs' / (name + '-sandbox.json')).read_text(encoding='utf-8'))
            assert receipt['runner_sha256'] == group['runner_sha256']
            assert receipt['sandbox_status'] == 'completed' and not receipt.get('cleanup_failed')


def test_recorded_feedback_relocates_dependency_and_retests_in_real_sandbox(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch)
    originals = [snapshot(root) for root in (args[0], args[1], args[3])]
    provider = Recorded(tmp_path / 'responses.json', [
        read_total(),
        patch('return value - FACTOR', 'return value', 0),
        action('read_symbol', path='pkg/rules.py', symbol='FACTOR'),
        read_total(),
        patch('return value', 'return value * FACTOR', 1),
    ])
    report = feedback.run(*args, llm=provider,
                          readable_files=['pkg/calc.py', 'pkg/rules.py', 'pkg/__init__.py'], source_root='.')
    assert report['status'] == 'ready_for_review' and report['accepted'], report
    assert report['counts']['requests'] == len(provider.calls) == 5
    assert report['counts']['reads'] == 3 and report['counts']['searches'] == 0
    assert report['counts']['applied_patches'] == report['workspace_revision'] == 2
    assert report['counts']['public_validations'] == 3
    assert report['counts']['rollbacks'] == 0
    assert report['fresh_model_calls'] == 0 and report['independent_grading_used'] is False
    assert report['original_inputs_unchanged']
    assert originals == [snapshot(root) for root in (args[0], args[1], args[3])]
    assert 'return value * FACTOR\n' in (args[-1] / 'workspace/pkg/calc.py').read_text(encoding='utf-8')

    # The constant is disclosed only after the explicit dependency read, never as an eager file dump.
    assert all('FACTOR = 2' not in json.dumps(messages) for messages in provider.messages[:3])
    assert 'FACTOR = 2' in json.dumps(provider.messages[3])
    reads = [row['result'] for row in report['actions'] if row.get('action') == 'read_symbol']
    assert [row['workspace_revision'] for row in reads] == [0, 1, 1]
    assert all(row['complete_symbol'] and row['content_hash'] and row['receipt_id'] for row in reads)
    validations = validation_reports(args[-1])
    assert len(validations) == 3
    assert_real_receipts(validations)
    assert sorted((row['public_checks']['Reproduce']['passed'],
                   row['public_checks']['Preserve']['passed']) for _, row in validations) == [
                       (False, False), (False, True), (True, True)]


def test_cancel_at_recorded_patch_response_prevents_publication_and_extra_validation(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch)
    originals = [snapshot(root) for root in (args[0], args[1], args[3])]
    provider = Recorded(tmp_path / 'responses.json', [
        read_total(), patch('return value - FACTOR', 'return value * FACTOR', 0),
    ], hook=lambda count: (args[-1] / 'CANCEL').touch() if count == 2 else None)
    report = feedback.run(*args, llm=provider,
                          readable_files=['pkg/calc.py', 'pkg/rules.py', 'pkg/__init__.py'], source_root='.')
    assert report['status'] == 'cancelled' and not report['accepted'], report
    assert report['counts']['requests'] == len(provider.calls) == 2
    assert report['counts']['applied_patches'] == report['workspace_revision'] == 0
    assert report['counts']['public_validations'] == 1 and report['fresh_model_calls'] == 0
    assert snapshot(args[-1] / 'workspace') == originals[1]
    assert report['original_inputs_unchanged']
    assert originals == [snapshot(root) for root in (args[0], args[1], args[3])]
    validations = validation_reports(args[-1])
    assert len(validations) == 1
    assert_real_receipts(validations)


def test_cancel_during_real_public_validation_kills_only_owned_containers(tmp_path, monkeypatch):
    args = prepared(tmp_path, monkeypatch)
    test_file = args[3] / 'test_admission.py'
    test_file.write_text(test_file.read_text(encoding='utf-8').replace(
        'self.assertEqual(total(3), 6)',
        '__import__("time").sleep(60)\n        self.assertEqual(total(3), 6)'), encoding='utf-8')
    originals = [snapshot(root) for root in (args[0], args[1], args[3])]
    provider = Recorded(tmp_path / 'responses.json', [action('finish')])
    outcomes, errors = [], []
    owned = ['ps', '-aq', '--filter', 'label=corecoder.sandbox.owner=' + runner.owner(args[-1])]

    def execute():
        try:
            outcomes.append(feedback.run(*args, llm=provider, timeout=60, source_root='.'))
        except Exception as exc:  # noqa: BLE001 - propagate background failures through the test thread
            errors.append(exc)

    thread = threading.Thread(target=execute, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while thread.is_alive() and time.monotonic() < deadline:
            # A running owned container proves validation reached the real sandbox.
            if runner.control(['ps', '-q', *owned[2:]], timeout=5).strip():
                break
            time.sleep(0.05)
        else:
            pytest.fail('Validation did not start an owned container: ' + repr(errors or outcomes))
        (args[-1] / 'CANCEL').touch()
        thread.join(30)
        assert not thread.is_alive(), 'Cancellation did not stop the validation worker'
        assert not errors, errors
        report = outcomes[0]
        assert report['status'] == 'cancelled' and not report['accepted'], report
        assert report['counts']['requests'] == report['counts']['applied_patches'] == 0
        assert report['fresh_model_calls'] == 0 and not provider.calls
        assert report['original_inputs_unchanged']
        assert originals == [snapshot(root) for root in (args[0], args[1], args[3])]
        assert not runner.control(owned, timeout=5).strip()
    finally:
        args[-1].mkdir(parents=True, exist_ok=True)
        (args[-1] / 'CANCEL').touch()
        thread.join(30)
        if thread.is_alive():
            runner.cleanup(args[-1])
