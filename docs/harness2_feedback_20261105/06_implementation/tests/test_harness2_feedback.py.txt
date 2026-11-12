"""Harness adapter integration and saved-candidate accounting; no inference."""
import json
import shutil

import pytest

from evals.runner import changes, digest, snapshot
from integrations import harness2 as bridge
from integrations import harness2_feedback as feedback
from integrations.harness2_context import DEFAULT, POLICY_FILE


def rollout(tmp_path):
    source, folder, checks = [tmp_path / name for name in ('source', 'execution', 'public')]
    source.mkdir()
    checks.mkdir()
    (source / 'code.py').write_text('def f(): return 1\n', encoding='utf-8')
    (checks / 'test_admission.py').write_text('# developer checks', encoding='utf-8')
    public = {'instance_id': 'example', 'repo': 'local/example', 'base_commit': 'a' * 40,
              'problem_statement': 'f should return 3'}
    bridge.write(folder / 'public.json', public)
    hints = {**dict.fromkeys(bridge.FILES, 'fixed guidance'), POLICY_FILE: json.dumps(DEFAULT)}
    job = {'kind': 'rollout', 'source': str(source), 'source_hash': digest(snapshot(source)),
           'public_sha256': bridge.sha(folder / 'public.json'), 'harness': hints, 'harness_sha256': 'fixed',
           'context_enabled': True, 'scripted': False, 'experiment_id': 'trial', 'task_id': 'example',
           'harness_variant': 'agg1', 'public_feedback': feedback.options(checks, 'pkg')}
    bridge.write(folder / 'job.json', job)
    shutil.copytree(source, folder / 'agent/workspace')
    (folder / 'agent/workspace/code.py').write_text('def f(): return 2\n', encoding='utf-8')
    changed, patch = changes(snapshot(source), snapshot(folder / 'agent/workspace'))
    (folder / 'agent/patch.diff').write_text(patch, encoding='utf-8', newline='\n')
    bridge.write(folder / 'agent/report.json', {'changed_files': changed,
        'patch_sha256': bridge.sha(folder / 'agent/patch.diff'), 'fresh_model_calls': 4,
        'metrics': {'prompt_tokens': 90, 'completion_tokens': 10}})
    bridge.write(folder / 'agent/baseline-files.json', {'code.py': bridge.sha(source / 'code.py')})
    return folder, job


def test_public_check_configuration_is_frozen_and_unknown_fields_rejected(tmp_path):
    folder, job = rollout(tmp_path)
    feedback.verify_options(job['public_feedback'])
    with pytest.raises(ValueError):
        feedback.verify_options({**job['public_feedback'], 'private_checks': 'forbidden'})
    (tmp_path / 'public/test_admission.py').write_text('modified', encoding='utf-8')
    with pytest.raises(ValueError, match='changed'):
        feedback.verify_options(job['public_feedback'])
    assert folder.exists()


def test_continuation_passes_guidance_policy_and_twenty_rounds_without_private_case(tmp_path, monkeypatch):
    from repairflow import feedback_repair
    folder, job = rollout(tmp_path)
    source = tmp_path / 'source'
    (source / 'MANIFEST.in').write_text('include LICENSE\n', encoding='utf-8')
    job['source_hash'] = digest(snapshot(source))
    bridge.write(folder / 'job.json', job)
    captured = {}

    def run(*args, **kwargs):
        assert (args[1] / 'MANIFEST.in').read_text(encoding='utf-8') == 'include LICENSE\n'
        captured.update(args=args, kwargs=kwargs)
        return {'status': 'ready_for_review', 'accepted': True, 'feedback_rounds_attempted': 2}

    monkeypatch.setattr(feedback_repair, 'run', run)
    feedback.continue_rollout(folder / 'job.json')
    assert captured['kwargs']['max_feedback_rounds'] == 20
    assert captured['kwargs']['context_policy'] == DEFAULT
    assert captured['kwargs']['guidance'] == 'fixed guidance\n\nfixed guidance'
    assert captured['kwargs']['trace_metadata']['harness_variant'] == 'agg1'
    assert captured['args'][2] == ['code.py']
    assert 'checks' not in captured['args'][5]  # Only public task fields reach the model.
    assert bridge.read(folder / 'execution.json')['feedback_rounds_attempted'] == 2
    assert feedback.artifact_dir(folder) == folder / 'feedback'


def test_saved_candidate_is_hash_checked_and_original_usage_is_not_counted_as_fresh(tmp_path, monkeypatch):
    folder, job = rollout(tmp_path)
    new = tmp_path / 'continuation'
    new.mkdir()
    # workspace() enforces project .tmp for actual CLI, not pytest's exported test roots.
    monkeypatch.setattr(feedback, 'workspace', lambda path: path)
    feedback.restore_candidate({**job, 'reuse_rollout': folder}, new)
    assert bridge.sha(folder / 'agent/report.json') == bridge.sha(new / 'agent/report.json')
    bridge.write(new / 'job.json', job)
    bridge.write(new / 'execution.json', {'artifact_directory': 'feedback'})
    bridge.write(new / 'feedback/report.json', {'fresh_model_calls': 2,
        'metrics': {'prompt_tokens': 20, 'completion_tokens': 8}})
    summary = feedback.summary(new)
    assert summary['fresh_model_calls'] == 2 and summary['actual_tokens'] == 28
    assert summary['phases'][0]['reused'] and summary['phases'][0]['tokens'] == 0
    (folder / 'agent/workspace/code.py').write_text('tampered\n', encoding='utf-8')
    with pytest.raises(ValueError, match='reconstruct'):
        feedback.restore_candidate({**job, 'reuse_rollout': folder}, tmp_path / 'rejected')


def test_new_candidate_and_feedback_usage_both_count_and_unknown_usage_stays_unknown(tmp_path):
    folder, _job = rollout(tmp_path)
    bridge.write(folder / 'execution.json', {'artifact_directory': 'feedback'})
    bridge.write(folder / 'feedback/report.json', {'fresh_model_calls': 1,
        'metrics': {'prompt_tokens': None, 'completion_tokens': 4}})
    summary = feedback.summary(folder)
    assert summary['fresh_model_calls'] == 5 and summary['actual_tokens'] is None
    bridge.write(folder / 'feedback/report.json', {'fresh_model_calls': 0, 'metrics': {}})
    assert feedback.summary(folder)['actual_tokens'] == 100


@pytest.mark.parametrize('enabled', [False, True])
def test_worker_reaches_feedback_after_candidate_only_when_explicitly_enabled(tmp_path, monkeypatch, enabled):
    from evals import local50_unmetered as local
    folder, job = rollout(tmp_path)
    if not enabled:
        job.pop('public_feedback')
    bridge.write(folder / 'job.json', job)
    calls = []
    monkeypatch.setattr(local, 'worker', lambda path: calls.append('candidate'))
    monkeypatch.setattr(feedback, 'continue_rollout', lambda path: calls.append('feedback'))
    bridge.worker(folder / 'job.json')
    assert calls == (['candidate', 'feedback'] if enabled else ['candidate'])


def test_grader_rejects_modified_final_workspace_before_private_tests(tmp_path):
    folder, _ = rollout(tmp_path)
    bridge.write(folder / 'execution.json', {'artifact_directory': 'feedback'})
    shutil.copytree(folder / 'agent/workspace', folder / 'feedback/workspace')
    bridge.write(folder / 'feedback/report.json', {'final_candidate_hash': 'not-the-current-hash'})
    with pytest.raises(ValueError, match='changed after termination'):
        feedback.grade({}, folder)


def test_publication_summary_requires_termination_and_does_not_forward_private_details():
    from deploy.langfuse.harness2_feedback import public_summary
    report = {'status': 'completed', 'usage': {'fresh_model_calls': 2, 'actual_tokens': 100},
              'execution': {'initial_candidate_reused': True}, 'grading': 'PRIVATE_SENTINEL'}
    phase = {'independent_grading_used': False, 'feedback_rounds_attempted': 2, 'accepted': True}
    assert 'PRIVATE_SENTINEL' not in json.dumps(public_summary(report, phase))
    with pytest.raises(ValueError):
        public_summary({**report, 'status': 'running'}, phase)
