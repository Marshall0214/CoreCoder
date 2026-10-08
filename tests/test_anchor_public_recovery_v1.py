import json
from types import SimpleNamespace

import pytest

from docs.experiments import anchor_public_recovery_v1 as recovery
from evals.runner import digest, snapshot


def job_with_snapshot(tmp_path):
    root = tmp_path / 'task'
    original = root / 'initial-workspace'
    workspace = root / 'anchor-public' / 'workspace'
    harness = tmp_path / 'checks'
    for p in (original, workspace, harness):
        p.mkdir(parents=True)
    source = 'def first():\n    return 1\n'
    (original / 'code.py').write_text(source)
    (workspace / 'code.py').write_text(source)
    (harness / 'test_admission.py').write_text('PUBLIC_BOUNDARY_EXPECTATION = []\n')
    job = {'workspace': str(workspace), 'allowed_files': ['code.py'], 'evidence': [],
           'description': 'public', 'package': 'example', 'source_root': '.',
           'harness': str(harness), 'harness_hash': digest(snapshot(harness)), 'public_initial': {}}
    return job, workspace.parent, source


def test_resubmission_contains_both_feedbacks_with_one_request(tmp_path, monkeypatch):
    job, root, _ = job_with_snapshot(tmp_path)
    monkeypatch.setattr(recovery.policy.repair, 'validate_evidence', lambda *a: None)
    monkeypatch.setattr(recovery.policy, 'diagnostic', lambda *a: 'public failure: empty iterator')
    seen = []

    def chat(messages, **kwargs):
        seen.append((messages, kwargs))
        return SimpleNamespace(content=json.dumps({'edits': []}), tool_calls=[])

    recovery.resubmit(SimpleNamespace(chat=chat), job, root, {'sequential_match_count': 2})
    assert len(seen) == 1 and seen[0][1] == {'tools': []}
    payload = json.loads(seen[0][0][1]['content'])
    assert payload['edit_transaction_feedback']['sequential_match_count'] == 2
    assert 'PUBLIC_BOUNDARY_EXPECTATION' in payload['public_check_feedback']['test_code']
    assert 'empty iterator' in payload['public_check_feedback']['observations']
    assert set(payload) == {'description', 'allowed_files', 'fragments',
                            'edit_transaction_feedback', 'public_check_feedback'}


def test_changed_harness_blocks_model_call(tmp_path, monkeypatch):
    job, root, _ = job_with_snapshot(tmp_path)
    monkeypatch.setattr(recovery.policy.repair, 'validate_evidence', lambda *a: None)
    (recovery.Path(job['harness']) / 'test_admission.py').write_text('changed')
    llm = SimpleNamespace(chat=lambda *a, **kw: pytest.fail('model must not run'))
    with pytest.raises(ValueError, match='harness changed'):
        recovery.resubmit(llm, job, root, {})


@pytest.mark.parametrize('bad_group', ['Reproduce', 'Preserve'])
def test_failed_public_group_restores_first_snapshot(tmp_path, monkeypatch, bad_group):
    job, root, original = job_with_snapshot(tmp_path)
    source = recovery.Path(job['workspace']) / 'code.py'
    source.write_text('def first():\n    return 2\n')
    groups = {g: {'passed': g != bad_group} for g in ('Reproduce', 'Preserve')}
    monkeypatch.setattr(recovery.policy, 'public_check', lambda *a: groups)
    result = recovery.retain_checked(job, root, {'status': 'completed'})
    assert result['status'] == 'public_checks_failed' and not result['retained']
    assert source.read_text() == original


def test_public_verifier_exception_also_restores_snapshot(tmp_path, monkeypatch):
    job, root, original = job_with_snapshot(tmp_path)
    source = recovery.Path(job['workspace']) / 'code.py'
    source.write_text('def first():\n    return 2\n')

    def failed(*args):
        raise RuntimeError('verifier unavailable')

    monkeypatch.setattr(recovery.policy, 'public_check', failed)
    result = recovery.retain_checked(job, root, {'status': 'completed'})
    assert source.read_text() == original and not result['retained']
    assert 'unavailable' in result['public_error']


def test_successful_public_groups_retain_patch(tmp_path, monkeypatch):
    job, root, _ = job_with_snapshot(tmp_path)
    source = recovery.Path(job['workspace']) / 'code.py'
    source.write_text('def first():\n    return 2\n')
    monkeypatch.setattr(recovery.policy, 'public_check', lambda *a: {g: {'passed': True} for g in ('Reproduce', 'Preserve')})
    result = recovery.retain_checked(job, root, {'status': 'completed'})
    assert result['status'] == 'completed' and result['retained']
    assert 'return 2' in source.read_text()


def test_rejected_patch_never_triggers_public_verification(tmp_path, monkeypatch):
    job, root, _ = job_with_snapshot(tmp_path)
    monkeypatch.setattr(recovery.policy, 'public_check', lambda *a: pytest.fail('invalid patch must not be checked'))
    assert recovery.retain_checked(job, root, {'status': 'budget_exceeded'})['status'] == 'budget_exceeded'
