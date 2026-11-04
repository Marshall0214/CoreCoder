"""Slow transport recovery must retain bytes, validate shared layers and preserve inference."""
import hashlib
import json

import pytest

from evals.swebench_images import ImageTransfer
from evals.swebench_mini import sha, write
from evals.swebench_resume import ResumableTransfer, cache_link, requeue


def transfer(tmp_path, content):
    folder = tmp_path / 'batch/tasks/task/image-cache'
    folder.mkdir(parents=True)
    digest = hashlib.sha256(content).hexdigest()
    descriptor = {'digest': 'sha256:' + digest, 'size': len(content)}
    write(folder / 'manifest.json', {'config': descriptor, 'layers': []})
    return ResumableTransfer(folder), descriptor


def test_progress_can_continue_beyond_old_eighteen_attempts(tmp_path, monkeypatch):
    data = b'x' * 24
    tool, row = transfer(tmp_path, data)
    part = tool.folder / (row['digest'][7:] + '.part')
    calls = []

    def fetch(self, url, destination, header=None, resume=False, seconds=60):
        calls.append(seconds)
        with destination.open('ab') as stream:
            stream.write(b'x')
        return 28

    monkeypatch.setattr(ImageTransfer, 'fetch', fetch)
    assert tool.fetch('unused', part, resume=True) == 0
    assert len(calls) == 24 and sha(part) == row['digest'][7:]
    assert (tool.cache / row['digest'][7:]).read_bytes() == data


def test_stalled_download_returns_after_four_attempts(tmp_path, monkeypatch):
    tool, row = transfer(tmp_path, b'content')
    part = tool.folder / (row['digest'][7:] + '.part')
    calls = []
    monkeypatch.setattr(ImageTransfer, 'fetch', lambda *args, **kwargs: calls.append(1) or 28)
    assert tool.fetch('unused', part, resume=True) == 28
    assert len(calls) == 4


def test_wrong_checksum_is_not_cached(tmp_path, monkeypatch):
    tool, row = transfer(tmp_path, b'correct')
    part = tool.folder / (row['digest'][7:] + '.part')

    def fetch(self, url, destination, *args, **kwargs):
        destination.write_bytes(b'incorrc')
        return 0

    monkeypatch.setattr(ImageTransfer, 'fetch', fetch)
    assert tool.fetch('unused', part, resume=True) == 1
    assert not (tool.cache / row['digest'][7:]).exists()


def test_cached_layer_survives_task_cleanup_and_restores_without_download(tmp_path):
    tool, row = transfer(tmp_path, b'content')
    target = tool.folder / row['digest'][7:]
    target.write_bytes(b'content')
    assert tool.remember(target, row)
    target.unlink()
    tool.restore()
    assert target.read_bytes() == b'content'
    assert sha(target) == row['digest'][7:]


def test_only_preinference_image_errors_are_requeued_with_original_report_preserved(tmp_path):
    write(tmp_path / 'protocol.json', {'instance_ids': ['done', 'image', 'grading']})
    write(tmp_path / 'tasks/done/agent/report.json', {'status': 'agent_finished'})
    tasks = {'done': {'status': 'graded', 'resolved': True, 'fresh_model_calls': 1},
             'image': {'status': 'infra_error', 'phase': 'image', 'error_type': 'OSError'},
             'grading': {'status': 'infra_error', 'phase': 'grading', 'fresh_model_calls': 1}}
    write(tmp_path / 'report.json', {'tasks': tasks})
    original = (tmp_path / 'report.json').read_bytes()
    digest = sha(tmp_path / 'tasks/done/agent/report.json')
    requeue(tmp_path, tmp_path / 'recovery/one')
    report = json.loads((tmp_path / 'report.json').read_text(encoding='utf-8'))
    assert report['tasks']['done'] == tasks['done']
    assert report['tasks']['image']['status'] == 'preparing'
    assert report['tasks']['grading'] == tasks['grading']
    assert (tmp_path / 'recovery/one/report-before.json').read_bytes() == original
    assert sha(tmp_path / 'tasks/done/agent/report.json') == digest
    assert (tmp_path / 'recovery/one/transport-source.py').exists()


def test_image_retry_after_inference_is_rejected(tmp_path):
    write(tmp_path / 'report.json', {'tasks': {'task': {'status': 'infra_error', 'phase': 'image'}}})
    (tmp_path / 'tasks/task/agent').mkdir(parents=True)
    with pytest.raises(ValueError, match='after any inference'):
        requeue(tmp_path, tmp_path / 'recovery/one')
    assert not (tmp_path / 'recovery/one').exists()


def test_cache_works_when_windows_prohibits_hardlinks(tmp_path, monkeypatch):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'verified data')

    def reject(*args):
        raise PermissionError('hardlinks unavailable')

    monkeypatch.setattr('evals.swebench_resume.os.link', reject)
    cache_link(source, target)
    assert target.read_bytes() == source.read_bytes()
