"""Old small fixtures exercise the current Agent without grading-answer exposure."""
import json
import shutil

import pytest

from deploy.langfuse.local50 import scores, verify
from evals.local50 import export, fixture_controls, grade, scripted_smoke, summarize, worker
from evals.runner import digest, snapshot
from evals.swebench_mini import sha, write
from repairflow.issue_providers import UsageResponse
from sandbox.runner import SandboxError


@pytest.fixture
def case(tmp_path):
    before, after, checks = (tmp_path / name for name in ('before', 'after', 'checks'))
    for folder in (before, after):
        (folder / 'pkg').mkdir(parents=True)
        (folder / 'pkg/code.py').write_text('def f():\n    return 1\n', encoding='utf-8', newline='\n')
    (after / 'pkg/code.py').write_text('def f():\n    return 2\n', encoding='utf-8', newline='\n')
    checks.mkdir()
    (checks / 'test_admission.py').write_text('PRIVATE-GRADING-MARKER', encoding='utf-8')
    return {'task_id': 'simple', 'repo': 'example/pkg', 'package': 'pkg', 'source_root': '.',
            'before': str(before), 'after': str(after), 'checks': str(checks), 'allowed_files': ['pkg/code.py'],
            'description': 'f should return 2', 'before_hash': digest(snapshot(before))}


def group_result(passed):
    return {'passed': passed, 'tests_run': 1, 'successful': passed, 'returncode': 0 if passed else 1}


def fake_verify(case, source, logs):
    correct = 'return 2' in (source / 'pkg/code.py').read_text(encoding='utf-8')
    return {'passed': correct, 'scope_violations': [],
            'groups': {'Target': group_result(correct), 'Controls': group_result(True)}}


def test_export_omits_history(tmp_path):
    source = tmp_path / 'source'
    (source / '.git').mkdir(parents=True)
    (source / '.git/HEAD').write_text('future-history')
    (source / 'code.py').write_text('pass\n')
    export(source, tmp_path / 'workspace')
    assert not (tmp_path / 'workspace/.git').exists()
    assert (tmp_path / 'workspace/code.py').read_text() == 'pass\n'


def test_controls_detect_bug_reference_and_reuse_logs(case, tmp_path, monkeypatch):
    calls = []

    def groups(source, harness, package, source_root, logs, names):
        calls.append(source)
        logs.mkdir()
        return {'Target': group_result('return 2' in (source / 'pkg/code.py').read_text()),
                'Controls': group_result(True)}

    monkeypatch.setattr('repairflow.checks.groups', groups)
    folder = tmp_path / 'trial'
    folder.mkdir()
    result = fixture_controls(case, folder)
    assert not result['unchanged']['Target']['passed'] and result['reference']['Target']['passed']
    assert fixture_controls(case, folder) == result and len(calls) == 2


def test_scripted_smoke_reads_edits_and_grades_without_model(case, tmp_path, monkeypatch):
    monkeypatch.setattr('repairflow.checks.verify', fake_verify)
    folder = tmp_path / 'smoke'
    scripted_smoke(case, folder)
    result = json.loads((folder / 'smoke.json').read_text())
    assert result['resolved'] and result['fresh_model_calls'] == 0
    actions = json.loads((folder / 'agent/actions.json').read_text())
    assert [row['action'] for row in actions] == ['read_file', 'apply_patch', 'finish']
    assert 'return 2' in (folder / 'agent/workspace/pkg/code.py').read_text()


def test_worker_only_sends_public_task_and_baseline(case, tmp_path, monkeypatch):
    folder = tmp_path / 'trial'
    task = {'instance_id': 'simple', 'repo': 'example/pkg', 'base_commit': 'source-sha256:' + case['before_hash'],
            'problem_statement': case['description']}
    write(folder / 'public.json', task)
    write(folder / 'job.json', {'source': case['before'], 'source_hash': case['before_hash'],
                               'public_sha256': sha(folder / 'public.json')})
    responses = iter([{'action': 'read_file', 'arguments': {'path': 'pkg/code.py'}},
                      {'action': 'apply_patch', 'arguments': {'edits': [
                          {'file': 'pkg/code.py', 'old': 'return 1', 'new': 'return 2'}]}},
                      {'action': 'finish', 'arguments': {}}])

    class Provider:
        model = 'qwen3.5:27b'
        usage_source = 'ollama_response'

        def __init__(self):
            self.calls = []

        def chat(self, messages, **kwargs):
            text = json.dumps(messages)
            assert 'PRIVATE-GRADING-MARKER' not in text
            assert case['after'] not in text and case['checks'] not in text
            return UsageResponse(content=json.dumps(next(responses)),
                                 reported_usage={'prompt_tokens': 10, 'completion_tokens': 2})

    monkeypatch.setenv('CORECODER_LANGFUSE_ENABLED', '0')
    monkeypatch.setattr('evals.local50.OllamaProvider', lambda *args: Provider())
    worker(folder / 'job.json')
    report = json.loads((folder / 'agent/report.json').read_text())
    assert report['status'] == 'agent_finished' and report['changed_files'] == ['pkg/code.py']
    monkeypatch.setattr('repairflow.checks.verify', fake_verify)
    assert grade(case, folder)['resolved']


def test_candidate_execution_failure_is_unresolved(case, tmp_path, monkeypatch):
    folder = tmp_path / 'smoke'
    monkeypatch.setattr('repairflow.checks.verify', fake_verify)
    scripted_smoke(case, folder)
    fresh = tmp_path / 'fresh'
    shutil.copytree(folder / 'agent', fresh / 'agent')

    def fail(*args):
        raise SandboxError('sandbox_invalid_result')

    monkeypatch.setattr('repairflow.checks.verify', fail)
    result = grade(case, fresh)
    assert not result['resolved'] and result['candidate_execution_failure'] == 'sandbox_invalid_result'


def test_summary_separates_controls_from_inference():
    result = summarize({'a': {'controls_passed': True, 'status': 'preparing'},
                        'b': {'controls_passed': True, 'status': 'graded', 'resolved': False,
                              'fresh_model_calls': 4, 'total_tokens': 20, 'nonempty_patch': False,
                              'agent_status': 'repeated_action_limit'}})
    assert result['scheduled'] == 50 and result['controls_passed'] == 2
    assert result['agent_attempts'] == 1 and result['fresh_model_calls'] == 4
    assert result['graded'] == 1 and result['resolved'] == 0


def test_scores_and_receipt_do_not_claim_swebench_resolution():
    output = {'instance_id': 'a', 'resolved': False, 'total_tokens': 20, 'fresh_model_calls': 4}
    expected = scores(output)
    assert 'official_resolved' not in expected and expected['local_target_controls_passed'] == 0
    row = {'output': output, 'endTime': 'now', 'experimentId': 'exp', 'experimentDatasetId': 'dataset',
           'scores': [{'name': name, 'value': value} for name, value in expected.items()]}
    assert verify([row], 'dataset', 'exp', {'a': output})
    assert not verify([row, row], 'dataset', 'exp', {'a': output})
