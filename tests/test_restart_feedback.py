import json

import pytest

from corecoder.llm import LLMResponse
from docs.experiments import restart_feedback_worker_v1 as worker
from docs.experiments import tentative_feedback_worker_v1 as old
from tests.test_tentative_feedback import setup


@pytest.mark.parametrize('policy', ['continue', 'restart'])
def test_feedback_uses_selected_source_and_real_public_checks(tmp_path, monkeypatch, policy):
    second_old = 'return 1' if policy == 'restart' else 'return 2'
    root, job, events, llm, raw = setup(tmp_path, monkeypatch, [('return 1', 'return 2'), (second_old, 'return 3')])
    def chat(messages, tools=None):
        count = len(raw.messages); raw.messages.append(messages)
        edit = {'file': 'src/pkg/__init__.py', 'old': 'return 1' if count == 0 else second_old,
                'new': 'return 2' if count == 0 else 'return 3'}
        return LLMResponse(content=json.dumps({'edits': [edit]}), prompt_tokens=100, completion_tokens=100)
    monkeypatch.setattr(raw, 'chat', chat)
    monkeypatch.setattr(worker, 'canonical_check', old.tentative.canonical_check)
    job['restart_policy'] = policy
    result = worker.run_candidate(llm, job, events)
    data = json.loads(raw.messages[1][1]['content'])
    assert second_old in data['fragments'][0]['content']
    assert result['public_checks']['candidate']['passed'] is False
    assert result['public_checks']['final']['passed']
    assert len(raw.messages) == 2 and llm.metrics()['budget_accounted_tokens'] == 400
    assert (root/'src/pkg/__init__.py').read_text() == 'def f():\n    return 3\n'
    if policy == 'restart':
        assert result['restart']['task_start_exact']
        assert data['feedback_source_version']['failure_origin'].startswith('discarded')
    else:
        assert 'restart' not in result and 'feedback_source_version' not in data


def test_first_success_does_not_restart(tmp_path, monkeypatch):
    _root, job, events, llm, raw = setup(tmp_path, monkeypatch, [('return 1', 'return 3')])
    monkeypatch.setattr(worker, 'canonical_check', old.tentative.canonical_check)
    job['restart_policy'] = 'restart'
    result = worker.run_candidate(llm, job, events)
    assert 'restart' not in result and len(raw.messages) == 1
    assert result['status'] == 'completed'


@pytest.mark.parametrize('mutation', ['external', 'new_file', 'outside_scope'])
def test_restart_rejects_changed_or_out_of_scope_snapshot(tmp_path, mutation):
    p = tmp_path/'a.py'; p.write_bytes(b'old\r\n')
    start = worker.guard.files(tmp_path)
    p.write_bytes(b'candidate\r\n')
    candidate = worker.guard.files(tmp_path)
    allowed = ['a.py']
    if mutation == 'external': p.write_bytes(b'external')
    elif mutation == 'new_file':
        (tmp_path/'new.py').write_bytes(b'new')
        candidate = worker.guard.files(tmp_path)
    else: allowed = []
    before = worker.guard.files(tmp_path)
    with pytest.raises(ValueError): worker.restore_start(tmp_path, start, candidate, allowed)
    assert worker.guard.files(tmp_path) == before


def test_restart_preserves_exact_bytes(tmp_path):
    p = tmp_path/'a.py'; p.write_bytes(b'old\r\n')
    start = worker.guard.files(tmp_path)
    p.write_bytes(b'new\n')
    result = worker.restore_start(tmp_path, start, worker.guard.files(tmp_path), ['a.py'])
    assert result['restored'] and worker.guard.files(tmp_path) == start
