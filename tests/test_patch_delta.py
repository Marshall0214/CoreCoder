import hashlib
import json
import sys

import pytest

from docs.experiments import patch_delta_context_v1 as delta
from docs.experiments import patch_delta_worker_v1 as worker
from docs.experiments import tentative_feedback_worker_v1 as old
from tests.test_edited_context import bundle
from tests.test_tentative_feedback import setup


def test_removed_branch_history_current_anchors_and_budget(tmp_path):
    base = bundle(tmp_path, 'def first(value=None):\n    if value is None:\n        value = 1\n    return value\n\ndef second():\n    return 2\n')
    before = delta.guard.files(tmp_path)
    current = bundle(tmp_path, 'def first(value=None):\n    return value\n\ndef second():\n    return 2\n')
    result = delta.pack(tmp_path, ['app.py'], current, [{'path': 'app.py', 'symbol': 'first'}], before)
    row = result['patch_history']['files'][0]
    assert '-    if value is None:' in row['diff'] and '-        value = 1' in row['diff']
    assert row['before_sha256'] == hashlib.sha256(before['app.py']).hexdigest()
    assert row['current_sha256'] == result['evidence'][0]['content_hash']
    assert 'if value is None' not in result['evidence'][0]['content']
    assert result['metadata']['combined_chars'] <= 6000
    assert base['evidence'][0]['content_hash'] != row['current_sha256']


def test_optional_fragments_displaced_without_truncating_history(tmp_path):
    bundle(tmp_path)
    before = delta.guard.files(tmp_path)
    current = bundle(tmp_path, 'def first():\n    return 9\n\ndef second():\n    return 2\n')
    cost = len(delta.retention.contracts.encoded(delta.history(before, tmp_path, ['app.py'])))
    first = next(r for r in current['evidence'] if r['symbol'] == 'first')
    result = delta.pack(tmp_path, ['app.py'], current, [{'path': 'app.py', 'symbol': 'first'}], before,
                        limit=cost+len(first['content']))
    assert len(result['evidence']) == 1 and '-    return 1' in result['patch_history']['files'][0]['diff']
    assert result['metadata']['combined_chars'] == result['metadata']['max_chars']


def test_unchanged_source_has_no_history(tmp_path):
    base = bundle(tmp_path)
    assert delta.pack(tmp_path, ['app.py'], base, [], delta.guard.files(tmp_path)) is base


def test_history_does_not_make_old_snippet_a_valid_edit_anchor(tmp_path):
    bundle(tmp_path)
    before = delta.guard.files(tmp_path)
    current = bundle(tmp_path, 'def first():\n    return 9\n\ndef second():\n    return 2\n')
    packed = delta.pack(tmp_path, ['app.py'], current, [{'path': 'app.py', 'symbol': 'first'}], before)
    patch = json.dumps({'edits': [{'file': 'app.py', 'old': 'return 1', 'new': 'return 3'}]})
    result = delta.guard.transact(patch, tmp_path, ['app.py'], packed['evidence'],
                                  tmp_path.parent/(tmp_path.name+'-transaction'), sys.executable, [{'module': 'app', 'root': '.', 'path': 'app.py'}])
    assert not result['committed'] and result['reason'] == 'invalid_patch'
    assert 'return 9' in (tmp_path/'app.py').read_text()


@pytest.mark.parametrize('mutation', ['created', 'deleted', 'scope', 'large'])
def test_history_rejects_unrepresentable_or_over_budget_changes(tmp_path, mutation):
    base = bundle(tmp_path)
    before = delta.guard.files(tmp_path)
    allowed = ['app.py']
    if mutation == 'created':
        (tmp_path/'extra.py').write_text('x=1')
    elif mutation == 'deleted':
        (tmp_path/'app.py').unlink()
    elif mutation == 'scope':
        (tmp_path/'app.py').write_text('def first():\n    return 3\n')
        allowed = []
    else:
        base = bundle(tmp_path, 'def first():\n'+''.join(f'    value_{n} = {n}\n' for n in range(200)))
    with pytest.raises(delta.retention.ContextUnavailable):
        delta.pack(tmp_path, allowed, base, [], before)


@pytest.mark.parametrize('policy', ['baseline', 'patch-delta'])
def test_feedback_can_correct_first_patch_using_current_anchor(tmp_path, monkeypatch, policy):
    root, job, events, llm, raw = setup(tmp_path, monkeypatch, [('return 1', 'return 2'), ('return 2', 'return 3')])
    monkeypatch.setattr(worker, 'canonical_check', old.tentative.canonical_check)
    def chat(messages, tools=None):
        from corecoder.llm import LLMResponse
        call = len(raw.messages)
        assert (root/'src/pkg/__init__.py').read_text() == f'def f():\n    return {1 if call == 0 else 2}\n'
        raw.messages.append(messages)
        return LLMResponse(content=json.dumps({'edits': [{'file': 'src/pkg/__init__.py',
                           'old': f'return {1 if call == 0 else 2}', 'new': f'return {2 if call == 0 else 3}'}]}),
                           prompt_tokens=100, completion_tokens=100)
    monkeypatch.setattr(raw, 'chat', chat)
    job['history_policy'] = policy
    result = worker.run_candidate(llm, job, events)
    assert len(raw.messages) == 2 and result['public_checks']['final']['passed']
    first = json.loads(raw.messages[0][1]['content'])
    feedback = json.loads(raw.messages[1][1]['content'])
    assert 'patch_history' not in first
    assert ('patch_history' in feedback) == (policy == 'patch-delta')
    assert feedback['fragments'][0]['content'].splitlines() == ['def f():', '    return 2']
    if policy == 'patch-delta':
        assert '-    return 1' in feedback['patch_history']['files'][0]['diff']
    assert (root/'src/pkg/__init__.py').read_text() == 'def f():\n    return 3\n'
