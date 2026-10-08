import json
from pathlib import Path

import pytest

from docs.experiments import diagnostic_feedback_v1 as diagnosis
from evals.runtime import Events


def stderr(name, message):
    return (f'FAIL: {name}\n' + '-' * 70 + '\nTraceback (most recent call last):\n'
            '  File "public.py", line 4, in test_case\n    self.assertEqual(actual, expected)\n'
            f'AssertionError: {message}\n' + '-' * 70 + '\nRan 1 test\nFAILED\n')


def test_multiple_assertions_survive_long_traceback():
    text = stderr('target', 'missing output') + stderr('cleanup', 'context leaked')
    result = diagnosis.failures(text)
    assert [r['test'] for r in result] == ['FAIL: target', 'FAIL: cleanup']
    assert 'missing output' in result[0]['detail']
    assert 'context leaked' in result[1]['detail']
    assert 'Ran 1 test' not in result[1]['detail']


def test_diagnostics_are_bounded_and_mark_execution_failure():
    result = diagnosis.failures('discovery error: ' + 'x' * 10000)
    assert len(result[0]['detail']) == 480
    result = diagnosis.failures(''.join(stderr(str(i), 'x' * 1000) for i in range(20)))
    assert len(result) == 4 and all(len(r['detail']) <= 320 for r in result)


def test_balanced_feedback_preserves_normal_failure_and_success(tmp_path):
    harness = tmp_path / 'public'
    harness.mkdir()
    (harness / 'test_admission.py').write_text('readable public tests', encoding='utf-8')
    (tmp_path / 'initial-response.txt').write_text(
        '```json\n' + json.dumps({'edits': [{'file': 'code.py', 'old': 'return 0', 'new': 'return 1'}]}) + '\n```',
        encoding='utf-8')
    outcomes = {}
    for suite in ('public', 'frozen'):
        logs = tmp_path / ('initial-' + suite)
        logs.mkdir()
        outcomes[suite] = {}
        for group in ('Reproduce', 'Preserve'):
            passed = suite == 'frozen' and group == 'Preserve'
            outcomes[suite][group] = {'passed': passed, 'tests_run': 1, 'failures': int(not passed)}
            (logs / (group + '.stderr.txt')).write_text(stderr(group, 'bad ' + group), encoding='utf-8')
    result = diagnosis.feedback(outcomes, tmp_path / 'workspace',
                                {'harness': str(harness), 'frozen_harness': str(harness)}, tmp_path)
    assert len(result['groups']) == 4
    assert result['groups'][-1]['passed']
    assert 'diagnostic_index' not in result['groups'][-1]
    assert len(result['diagnostics']) == 2  # Duplicate failure details are shared across suites.
    assert 'bad Preserve' in json.dumps(result['diagnostics'])
    assert '+return 1' in result['initial_changes'][0]['diff']
    assert result['test_code'] == 'readable public tests'
    assert '2048' in result['repair_review'] and 'unique' in result['repair_review']


def test_only_feedback_hook_changes_and_is_restored(tmp_path, monkeypatch):
    original = diagnosis.guarded.feedback
    refresh = diagnosis.previous.refresh_seeds
    request = diagnosis.previous.request
    def run(llm, job, events):
        assert diagnosis.guarded.feedback is diagnosis.feedback
        assert diagnosis.previous.refresh_seeds is refresh and diagnosis.previous.request is request
        return {'status': 'completed'}
    monkeypatch.setattr(diagnosis.guarded, 'run_candidate', run)
    result = diagnosis.run_candidate(None, {}, Events(tmp_path / 'trace.jsonl', 'test'))
    assert result['protocol'] == 'diagnostic-feedback-v1'
    assert diagnosis.guarded.feedback is original


def test_feedback_hook_restored_on_error(tmp_path, monkeypatch):
    original = diagnosis.guarded.feedback
    def run(*args):
        raise RuntimeError('worker failed')
    monkeypatch.setattr(diagnosis.guarded, 'run_candidate', run)
    with pytest.raises(RuntimeError, match='worker failed'):
        diagnosis.run_candidate(None, {}, Events(Path(tmp_path) / 'trace.jsonl', 'test'))
    assert diagnosis.guarded.feedback is original
