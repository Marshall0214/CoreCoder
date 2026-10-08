import hashlib
import json
from types import SimpleNamespace

import pytest

from docs.experiments import exact_anchor_recovery_v1 as recovery


def setup_source(tmp_path, monkeypatch, source):
    path = tmp_path / 'code.py'
    path.write_text(source)
    evidence = [{'path': 'code.py', 'symbol': 'first', 'content': source,
                 'content_hash': hashlib.sha256(path.read_bytes()).hexdigest()}]
    monkeypatch.setattr(recovery.policy.repair, 'validate_evidence', lambda *args: None)
    return path, evidence


def test_duplicate_anchor_reports_count_and_does_not_write(tmp_path, monkeypatch):
    original = 'def first():\n    return 1\ndef second():\n    return 1\n'
    path, evidence = setup_source(tmp_path, monkeypatch, original)
    patch = json.dumps({'edits': [{'file': 'code.py', 'old': '    return 1', 'new': '    return 2'}]})
    result = recovery.diagnose(patch, tmp_path, ['code.py'], evidence)
    assert result['sequential_match_count'] == result['original_match_count'] == 2
    assert result['edit_index'] == 0 and result['none_committed']
    assert path.read_text() == original


def test_sequential_conflict_reports_zero_without_committing_valid_prefix(tmp_path, monkeypatch):
    original = 'def first():\n    return 1\n'
    path, evidence = setup_source(tmp_path, monkeypatch, original)
    edit = {'file': 'code.py', 'old': 'return 1', 'new': 'return 2'}
    result = recovery.diagnose(json.dumps({'edits': [edit, edit]}), tmp_path, ['code.py'], evidence)
    assert result['sequential_match_count'] == 0 and result['original_match_count'] == 1
    assert result['edit_index'] == 1
    assert path.read_text() == original


@pytest.mark.parametrize('edit', [
    {'file': '../outside.py', 'old': 'return 1', 'new': 'return 2'},
    {'file': 'code.py', 'old': 'not supplied', 'new': 'return 2'},
    {'file': 'code.py', 'old': '', 'new': 'return 2'},
])
def test_does_not_recover_out_of_scope_or_unseen_edits(tmp_path, monkeypatch, edit):
    _, evidence = setup_source(tmp_path, monkeypatch, 'def first():\n    return 1\n')
    assert recovery.diagnose(json.dumps({'edits': [edit]}), tmp_path, ['code.py'], evidence) is None


def test_stale_evidence_blocks_recovery_before_source_diagnosis(tmp_path, monkeypatch):
    _, evidence = setup_source(tmp_path, monkeypatch, 'def first():\n    return 1\n')

    def changed(*args):
        raise ValueError('Source version changed')

    monkeypatch.setattr(recovery.policy.repair, 'validate_evidence', changed)
    with pytest.raises(ValueError, match='version changed'):
        recovery.diagnose('{}', tmp_path, ['code.py'], evidence)


def test_recovery_with_invalid_python_cannot_write_over_original(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    logs = tmp_path / 'logs'
    logs.mkdir()
    original = 'def first():\n    return 1\n'
    path, evidence = setup_source(workspace, monkeypatch, original)
    patch = json.dumps({'edits': [{'file': 'code.py', 'old': 'return 1', 'new': 'return )'}]})
    llm = SimpleNamespace(chat=lambda *args, **kwargs: SimpleNamespace(content=patch, tool_calls=[]))
    job = {'workspace': str(workspace), 'allowed_files': ['code.py'], 'evidence': evidence, 'description': 'public'}
    result = recovery.resubmit(llm, job, logs, {'none_committed': True})
    assert result['status'] == 'invalid_patch' and path.read_text() == original
