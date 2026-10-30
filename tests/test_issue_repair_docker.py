"""Explicit offline acceptance through real containers, not real model inference."""
import json
import os

import pytest

from repairflow.bundles import write
from repairflow.issue_repair import execute
from tests.issue_repair_fixture import patch, prepare_fixture

pytestmark = pytest.mark.skipif(os.environ.get('CORECODER_RUN_DOCKER_TESTS') != '1',
                                reason='Opt in with a prebuilt local Docker sandbox image')


@pytest.mark.parametrize('succeeds', [True, False])
def test_real_prepared_issue_to_review_or_rollback(tmp_path, succeeds, monkeypatch):
    # Always Docker despite a legacy environment requesting a host test backend.
    monkeypatch.setenv('CORECODER_TEST_BACKEND', 'local')
    prepared, configuration = prepare_fixture(tmp_path, os.environ.get('CORECODER_SANDBOX_IMAGE'))
    responses = tmp_path / 'responses.json'
    write(responses, [patch()] if succeeds else [patch(new=4), '{}'])
    report = execute(prepared, configuration, tmp_path / 'run', mode='scripted', responses=responses)
    assert report['public_checks_passed'] is succeeds and report['accepted'] is False
    assert report['fresh_model_calls'] == 0 and report['original_unchanged']
    assert report['delivery_status'] == ('ready_for_review' if succeeds else 'not_delivered')
    assert bool((tmp_path / 'run/patch.diff').read_text()) is succeeds
    assert report['final_public_checks']['Preserve']['passed']


def test_real_symbol_read_and_third_edit_recovery(tmp_path):
    prepared, configuration = prepare_fixture(tmp_path, os.environ.get('CORECODER_SANDBOX_IMAGE'))
    responses = tmp_path / 'responses.json'
    read_action = json.dumps({'action': 'read_symbol', 'arguments': {'path': 'src/pkg/__init__.py', 'symbol': 'f'}})
    write(responses, [patch(old=77), read_action, patch(old=77), read_action, patch()])
    report = execute(prepared, configuration, tmp_path / 'run', mode='scripted', responses=responses,
                     workflow='symbol-recovery-v1', observation_policy='compact-v1')
    assert report['public_checks_passed'] and report['edit_attempts_used'] == 3
    assert report['scripted_calls'] == 5 and report['fresh_model_calls'] == 0
    assert report['final_public_checks']['Preserve']['passed'] and report['original_unchanged']
    assert report['accepted'] is False and report['delivery_status'] == 'ready_for_review'
    assert report['observation_policy'] == 'compact-v1'


def test_real_module_binding_reads_then_constant_edit(tmp_path):
    source = ('from operator import add as combine\nSTEP = 1\n'
              'def f(x):\n    return combine(x, STEP)\n\ndef g(x):\n    return x\n')
    prepared, configuration = prepare_fixture(tmp_path, os.environ.get('CORECODER_SANDBOX_IMAGE'), source=source)
    responses = tmp_path / 'responses.json'
    reads = [json.dumps({'action': 'read_symbol', 'arguments': {'path': 'src/pkg/__init__.py', 'symbol': name}})
             for name in ('STEP', 'combine')]
    write(responses, [*reads, json.dumps({'action': 'apply_patch', 'arguments': {'edits': [
        {'file': 'src/pkg/__init__.py', 'old': 'STEP = 1\n', 'new': 'STEP = 2\n'}]}})])
    report = execute(prepared, configuration, tmp_path / 'run', mode='scripted', responses=responses,
                     workflow='symbol-recovery-v1')
    assert report['public_checks_passed'] and report['edit_attempts_used'] == 1
    assert report['scripted_calls'] == 3 and report['fresh_model_calls'] == 0
    assert [a['result']['kind'] for a in report['actions'][:2]] == ['assignment', 'import']
    assert report['actions'][1]['result']['import_source']['followed'] is False
    assert report['final_public_checks']['Preserve']['passed'] and report['original_unchanged']
    assert (prepared / 'source/src/pkg/__init__.py').read_text(encoding='utf-8') == source
    assert report['accepted'] is False and report['delivery_status'] == 'ready_for_review'
