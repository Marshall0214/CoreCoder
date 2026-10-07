import hashlib
import json
import sys

import pytest

from docs.experiments import patch_transaction_v1 as guard


def setup_case(tmp_path, source='value = 1\n'):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'app.py').write_bytes(source.encode())
    evidence = [{'path': 'app.py', 'content': source,
                 'content_hash': hashlib.sha256(source.encode()).hexdigest()}]
    return workspace, evidence


def run(tmp_path, workspace, evidence, old, new, **kwargs):
    patch = json.dumps({'edits': [{'file': 'app.py', 'old': old, 'new': new}]})
    return guard.transact(patch, workspace, ['app.py'], evidence, tmp_path / 'transaction', sys.executable,
                          [{'module': 'app', 'root': '.', 'path': 'app.py'}], **kwargs)


@pytest.mark.parametrize('replacement,reason', [
    ('value = (', 'invalid_python'),
    ('return 2', 'invalid_python'),
    ('import typing\ndef f(x: typing.str_bytes): pass', 'import_failed'),
    ('def f(): pass\ndef f(): pass', 'added_duplicate_definitions'),
])
def test_invalid_candidate_never_changes_original(tmp_path, replacement, reason):
    workspace, evidence = setup_case(tmp_path)
    before = guard.files(workspace)
    result = run(tmp_path, workspace, evidence, 'value = 1', replacement)
    assert result['reason'] == reason and not result['committed']
    assert result['original_unchanged'] and guard.files(workspace) == before
    if reason in {'invalid_python', 'added_duplicate_definitions'}:
        assert result['import'] is None


def test_valid_candidate_commits_after_origin_checked_import(tmp_path):
    workspace, evidence = setup_case(tmp_path)
    result = run(tmp_path, workspace, evidence, 'value = 1', 'value = 2')
    assert result['accepted'] and result['import']['returncode'] == 0
    assert (workspace / 'app.py').read_text() == 'value = 2\n'


@pytest.mark.parametrize('source', [
    'from typing import overload as ov\n@ov\ndef f(x: int): ...\n@ov\ndef f(x: str): ...\ndef f(x): return x\n',
    'import typing as t\n@t.overload\ndef f(x: int): ...\ndef f(x): return x\n',
    'class C:\n @property\n def x(self): return 1\n @x.setter\n def x(self, v): pass\n',
    'if True:\n def f(): return 1\nelse:\n def f(): return 2\n',
    'def f(): pass\ndef f(): pass\n',
])
def test_existing_or_legitimate_definitions_are_not_new_duplicates(source):
    assert not guard.added_duplicates(source, source + '\nvalue = 2\n')


def test_new_class_method_duplicate_is_detected():
    source = 'class C:\n def f(self): return 1\n'
    assert guard.added_duplicates(source, source + ' def f(self): return 2\n')[0]['name'] == 'f'


def test_import_cannot_mutate_staged_source_and_get_committed(tmp_path):
    workspace, evidence = setup_case(tmp_path)
    replacement = "from pathlib import Path\nPath(__file__).write_text('value = 3')"
    result = run(tmp_path, workspace, evidence, 'value = 1', replacement)
    assert result['reason'] == 'import_mutated_source' and result['original_unchanged']


def test_stale_evidence_and_nonunique_anchor_are_rejected(tmp_path):
    workspace, evidence = setup_case(tmp_path, 'value = 1\nvalue = 1\n')
    result = run(tmp_path, workspace, evidence, 'value = 1', 'value = 2')
    assert result['reason'] == 'invalid_patch' and result['original_unchanged']
    evidence[0]['content_hash'] = 'stale'
    patch = json.dumps({'edits': [{'file': 'app.py', 'old': evidence[0]['content'], 'new': 'value = 2\n'}]})
    result = guard.transact(patch, workspace, ['app.py'], evidence, tmp_path / 'stale', sys.executable,
                            [{'module': 'app', 'root': '.', 'path': 'app.py'}])
    assert result['reason'] == 'invalid_patch' and result['original_unchanged']


def test_second_write_failure_rolls_back_both_files(tmp_path, monkeypatch):
    workspace, evidence = setup_case(tmp_path)
    (workspace / 'other.py').write_bytes(b'value = 1\n')
    evidence.append(dict(evidence[0], path='other.py'))
    patch = json.dumps({'edits': [{'file': name, 'old': 'value = 1', 'new': 'value = 2'}
                                  for name in ('app.py', 'other.py')]})
    before = guard.files(workspace)
    def fail(path, content):
        path.write_bytes(content)
        if path.name == 'other.py':
            raise OSError('simulated partial write')
    monkeypatch.setattr(guard, '_write', fail)
    result = guard.transact(patch, workspace, ['app.py', 'other.py'], evidence, tmp_path / 'tx', sys.executable,
                            [{'module': 'app', 'root': '.', 'path': 'app.py'}])
    assert result['reason'] == 'commit_failed' and guard.files(workspace) == before


def test_concurrent_source_change_does_not_get_overwritten(tmp_path, monkeypatch):
    workspace, evidence = setup_case(tmp_path)
    original = guard.run_process
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        (workspace / 'app.py').write_bytes(b'value = 99\n')
        return result
    monkeypatch.setattr(guard, 'run_process', mutate)
    result = run(tmp_path, workspace, evidence, 'value = 1', 'value = 2')
    assert result['reason'] == 'source_changed' and not result['committed']
    assert (workspace / 'app.py').read_bytes() == b'value = 99\n'


def test_output_cannot_be_nested_inside_workspace(tmp_path):
    workspace, evidence = setup_case(tmp_path)
    with pytest.raises(ValueError, match='outside'):
        guard.transact('{}', workspace, ['app.py'], evidence, workspace / 'tx', sys.executable,
                       [{'module': 'app', 'root': '.', 'path': 'app.py'}])
