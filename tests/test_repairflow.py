import hashlib
import json

import pytest

from corecoder.llm import LLMResponse
from repairflow.bundles import load, read, tree_hash, write
from repairflow.engine import execute
from tests.repair_bundle_fixture import bundle


@pytest.fixture(autouse=True)
def explicit_development_backend(monkeypatch):
    monkeypatch.setenv('CORECODER_TEST_BACKEND', 'local')


def test_real_replay_retrieves_applies_and_independently_verifies(tmp_path):
    task = bundle(tmp_path / 'sample')
    report = execute(task, 'replay', tmp_path / 'run')
    assert report['accepted'] and report['verification']['groups']['Target']['passed']
    assert report['fresh_model_calls'] == 0 and report['historical_usage_only']
    assert (task / 'source/src/pkg/__init__.py').read_text().startswith('def f(x):\n    return x + 1')
    assert '+    return x + 2' in (tmp_path / 'run/patch.diff').read_text()
    job = read(tmp_path / 'run/job.json')
    assert 'checks' not in job and 'grader' not in json.dumps(read(tmp_path / 'run/initial-messages.json'))
    assert (tmp_path / 'run/context-selection.json').exists()
    with pytest.raises(ValueError, match='fresh'):
        execute(task, 'replay', tmp_path / 'run')


def test_public_failure_rolls_back_and_cannot_reuse_replay_for_feedback(tmp_path):
    task = bundle(tmp_path / 'sample', bad=True)
    report = execute(task, 'replay', tmp_path / 'run')
    assert not report['accepted'] and report['original_unchanged']
    assert (tmp_path / 'run/patch.diff').read_text() == ''
    result = read(tmp_path / 'run/worker-result.json')
    assert result['feedback_attempts'] == 1 and result['correction']['status'] == 'invalid_patch'


@pytest.mark.parametrize('name', ['source/src/pkg/__init__.py', 'public/test_admission.py', 'grader/test_admission.py', 'replay.json'])
def test_tampered_bundle_rejected_before_execution(tmp_path, name):
    task = bundle(tmp_path / 'sample')
    with (task / name).open('a', encoding='utf-8') as stream:
        stream.write('\n# modified\n')
    with pytest.raises(ValueError, match='changed'):
        execute(task, 'replay', tmp_path / 'run')
    assert not (tmp_path / 'run').exists()


def test_replay_prompt_change_is_not_silently_accepted(tmp_path):
    task = bundle(tmp_path / 'sample')
    replay = read(task / 'replay.json')
    replay['prompt_hash'] = '0' * 64
    write(task / 'replay.json', replay)
    data = read(task / 'bundle.json')
    data['replay_sha256'] = hashlib.sha256((task / 'replay.json').read_bytes()).hexdigest()
    write(task / 'bundle.json', data)
    report = execute(task, 'replay', tmp_path / 'run')
    assert not report['accepted'] and report['fresh_model_calls'] == 0


def test_bundle_paths_cannot_escape_source(tmp_path):
    task = bundle(tmp_path / 'sample')
    data = read(task / 'bundle.json')
    data['allowed_files'] = ['../secret.py']
    write(task / 'bundle.json', data)
    with pytest.raises(ValueError, match='Unsafe'):
        load(task)


def test_independent_rejection_rolls_back_publicly_passing_candidate(tmp_path):
    task = bundle(tmp_path / 'sample')
    grading = task / 'grader/test_admission.py'
    grading.write_text(grading.read_text(encoding='utf-8').replace('f(1), 3', 'f(1), 5'), encoding='utf-8')
    data = read(task / 'bundle.json')
    data['hashes']['grader'] = tree_hash(task / 'grader')
    write(task / 'bundle.json', data)
    report = execute(task, 'replay', tmp_path / 'run')
    assert report['status'] == 'failed_verification'
    assert report['original_unchanged'] and not report['accepted']
    assert report['verification']['groups']['Controls']['passed']
    worker = read(tmp_path / 'run/worker-result.json')
    assert worker['published'] and worker['feedback_attempts'] == 0
    assert (tmp_path / 'run/patch.diff').read_text() == ''


def test_two_call_feedback_uses_current_source_and_never_grader(tmp_path):
    task = bundle(tmp_path / 'sample')

    class Sequence:
        model = 'deepseek-flash'

        def __init__(self):
            self.calls, self.messages = [], []

        def chat(self, messages, tools=None, **kwargs):
            self.messages.append(messages)
            second = bool(self.calls)
            self.calls.append({'test_response': True})
            patch = {'edits': [{'file': 'src/pkg/__init__.py', 'old': '    return x + ' + ('4' if second else '1'),
                                'new': '    return x + ' + ('2' if second else '4')}]}
            return LLMResponse(content=json.dumps(patch), prompt_tokens=100, completion_tokens=100)

        def close(self):
            pass

    responses = Sequence()
    report = execute(task, 'replay', tmp_path / 'run', provider_factory=lambda events: responses)
    assert report['accepted'] and report['metrics']['llm_calls'] == 2
    payload = json.loads(responses.messages[1][1]['content'])
    assert 'public_check_feedback' in payload and 'return x + 4' in json.dumps(payload['fragments'])
    assert 'grader' not in payload and str(task / 'grader') not in json.dumps(responses.messages)
