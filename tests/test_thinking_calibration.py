import io
import json

import pytest

from docs.experiments import thinking_calibration_v1 as calibration
from docs.experiments import thinking_calibration_worker_v1 as worker
from evals.runtime import Events


def test_offline_admission_needs_no_api_and_has_valid_positive_negative_cases(tmp_path, monkeypatch):
    monkeypatch.setattr(calibration, 'api', lambda *args: pytest.fail('Offline admission must not contact Ollama'))
    output = tmp_path / 'audit'
    calibration.run(output)
    report = json.loads((output / 'experiment.json').read_text(encoding='utf-8'))
    assert report['complete'] and not report['runs'] and len(report['admission']) == 4
    assert all(not r['original']['passed'] and r['reference']['passed'] for r in report['admission'])
    annotation = next(r for r in report['admission'] if r['task_id'] == 'annotation-import')
    assert not annotation['original']['import']['passed'] and annotation['original']['behavior']['tests_run'] == 0


@pytest.mark.parametrize('thinking', [False, True])
def test_native_request_explicit_toggle_and_no_reasoning_text_saved(tmp_path, monkeypatch, thinking):
    native = worker.NativeLLM({'model': 'test', 'thinking': thinking, 'base_url': 'http://127.0.0.1:11434'}, Events(tmp_path / 'trace.jsonl', 'test'))
    response = {'model': 'test', 'done': True, 'done_reason': 'stop', 'prompt_eval_count': 12, 'eval_count': 20,
                'message': {'content': '{"edits": []}', 'thinking': 'private reasoning example' if thinking else ''}}
    def request(req, timeout):
        data = json.loads(req.data)
        assert data['think'] is thinking and data['options']['temperature'] == 0
        assert data['options']['num_predict'] == 2048 and timeout == 120
        return io.StringIO(json.dumps(response))
    monkeypatch.setattr(worker.urllib.request, 'urlopen', request)
    result = native.chat([{'role': 'user', 'content': 'public'}], tools=[])
    assert result.content == '{"edits": []}' and native.telemetry['thinking_present'] == thinking
    assert 'private reasoning example' not in (tmp_path / 'trace.jsonl').read_text(encoding='utf-8')
    assert (tmp_path / 'response.txt').read_text(encoding='utf-8') == result.content


@pytest.mark.parametrize('reason,content,status', [('length', '', 'output_truncated'), ('stop', '', 'empty_final_answer')])
def test_worker_distinguishes_truncation_and_empty_final_answer(tmp_path, monkeypatch, reason, content, status):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'app.py').write_bytes(b'def value():\n    return 1\n')
    job = {'workspace': str(workspace), 'description': 'repair', 'allowed_files': ['app.py'],
           'files': calibration.evidence(workspace), 'thinking': True, 'model': 'test', 'base_url': 'http://127.0.0.1:11434'}
    path = tmp_path / 'job.json'
    path.write_text(json.dumps(job), encoding='utf-8')
    response = {'done': True, 'done_reason': reason, 'prompt_eval_count': 12, 'eval_count': 2048,
                'message': {'content': content, 'thinking': 'not persisted'}}
    monkeypatch.setattr(worker.urllib.request, 'urlopen', lambda *args, **kwargs: io.StringIO(json.dumps(response)))
    worker.worker(path)
    result = json.loads((tmp_path / 'worker-result.json').read_text(encoding='utf-8'))
    assert result['status'] == status and not result['patch_applied']
    assert result['metrics']['llm_calls'] == 1 and result['metrics']['budget_accounted_tokens'] == 2060
    assert (workspace / 'app.py').read_bytes() == b'def value():\n    return 1\n'


def test_structure_diagnostic_rejects_new_duplicate_even_when_behavior_passes(tmp_path):
    source, checks = tmp_path / 'source', tmp_path / 'checks.py'
    source.mkdir()
    original = 'class A:\n    def value(self):\n        return 1\n'
    (source / 'app.py').write_text(original + '    def value(self):\n        return 2\n', encoding='utf-8')
    checks.write_text('import unittest\nfrom app import A\nclass Checks(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(A().value(), 2)\n', encoding='utf-8')
    result = calibration.verify(source, checks, tmp_path / 'verification', original)
    assert result['import']['passed'] and result['behavior']['passed'] and not result['passed']
    assert result['structure']['added_duplicate_methods'] == [{'class': 'A', 'method': 'value', 'count': 2}]


@pytest.mark.parametrize('repeats', [0, 4, True])
def test_invalid_repeat_rejected_without_output(tmp_path, repeats):
    with pytest.raises(ValueError, match='Repeat'):
        calibration.run(tmp_path / 'unused', repeats)
    assert not (tmp_path / 'unused').exists()


def test_failed_provider_usage_is_unknown_in_summary():
    row = {'mode': 'on', 'accepted': False, 'worker': {'status': 'provider_error', 'native': {'response_received': False}},
           'verification': {'import': {'passed': False}, 'behavior': {'passed': False}}}
    assert calibration.summarize([row])['on']['provider_reported_total_tokens'] is None
