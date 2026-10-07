import json
import sys

import pytest

from corecoder.llm import LLMResponse
from docs.experiments import function_replace_v1 as replacement
from docs.experiments import function_replace_v2 as envelope
from docs.experiments import function_replace_worker_v1 as worker
from docs.experiments import tentative_feedback_worker_v1 as old
from tests.test_edited_context import bundle
from tests.test_tentative_feedback import setup


def edit(rows, symbol='first', new='def first():\n    return 9\n'):
    row = next(r for r in rows if r['symbol'] == symbol)
    return {'file': row['path'], 'symbol': symbol, 'content_hash': row['content_hash'], 'new': new}


def test_resolves_exact_function_without_model_old_text(tmp_path):
    rows = bundle(tmp_path)['evidence']
    before = (tmp_path/'app.py').read_bytes()
    content = json.dumps({'edits': [edit(rows)]})
    patch = replacement.lower(content, tmp_path, ['app.py'], rows)
    assert (tmp_path/'app.py').read_bytes() == before
    assert json.loads(patch)['edits'][0]['old'] == next(r['content'] for r in rows if r['symbol'] == 'first')
    result, _ = replacement.transact(content, tmp_path, ['app.py'], rows,
                                     tmp_path.parent/(tmp_path.name+'-transaction'), sys.executable,
                                     [{'module': 'app', 'root': '.', 'path': 'app.py'}])
    assert result['committed'] and 'return 9' in (tmp_path/'app.py').read_text()


@pytest.mark.parametrize('change', ['stale', 'undisplayed', 'partial', 'scope', 'wrong_name', 'extra_statement',
                                   'async_kind', 'duplicate_edit', 'invalid_python', 'model_line_number'])
def test_invalid_function_selection_or_body_has_no_writes(tmp_path, change):
    rows = bundle(tmp_path)['evidence']
    item = edit(rows)
    edits = [item]
    if change == 'stale': item['content_hash'] = '0'*64
    elif change == 'undisplayed': rows = [r for r in rows if r['symbol'] != 'first']
    elif change == 'partial': rows[0] = dict(rows[0], content='return 1')
    elif change == 'scope': item['file'] = '../app.py'
    elif change == 'wrong_name': item['new'] = 'def other():\n    return 9\n'
    elif change == 'extra_statement': item['new'] += '\nprint("extra")\n'
    elif change == 'async_kind': item['new'] = 'async '+item['new']
    elif change == 'duplicate_edit': edits.append(dict(item))
    elif change == 'invalid_python': item['new'] = 'def first(:'
    elif change == 'model_line_number': item['start_line'] = 1
    before = (tmp_path/'app.py').read_bytes()
    with pytest.raises(ValueError):
        replacement.lower(json.dumps({'edits': edits}), tmp_path, ['app.py'], rows)
    assert (tmp_path/'app.py').read_bytes() == before


def test_file_changed_after_reading_cannot_be_replaced(tmp_path):
    rows = bundle(tmp_path)['evidence']
    item = edit(rows)
    (tmp_path/'app.py').write_text('def first():\n    return 5\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Stale'):
        replacement.lower(json.dumps({'edits': [item]}), tmp_path, ['app.py'], rows)


def test_duplicate_definition_is_ambiguous_even_if_index_overwrites_it(tmp_path):
    rows = bundle(tmp_path, 'def first():\n    return 1\n\ndef first():\n    return 2\n')['evidence']
    with pytest.raises(ValueError, match='uniquely'):
        replacement.lower(json.dumps({'edits': [edit(rows)]}), tmp_path, ['app.py'], rows)


def test_nested_parent_child_batch_is_rejected(tmp_path):
    rows = bundle(tmp_path, 'def first():\n    def child():\n        return 1\n    return child()\n')['evidence']
    parent = rows[0]
    lines = (tmp_path/'app.py').read_bytes().decode().splitlines(True)
    rows.append(dict(parent, symbol='first.child', start_line=2, end_line=3, content=''.join(lines[1:3])))
    edits = [edit(rows, new='def first():\n    return 9\n'), edit(rows, 'first.child', 'def child():\n    return 9\n')]
    with pytest.raises(ValueError, match='overlapping'):
        replacement.lower(json.dumps({'edits': edits}), tmp_path, ['app.py'], rows)


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_decorated_method_indent_and_line_endings_preserved(tmp_path, newline):
    source = 'class Item:\n    @staticmethod\n    def first():\n        return 1\n'
    bundle(tmp_path, source)
    (tmp_path/'app.py').write_bytes(source.replace('\n', newline).encode())
    from docs.experiments.function_index_audit_v1 import FunctionIndex, pack
    index = FunctionIndex(tmp_path, ['app.py']); index.refresh(); rows = pack(index, index.rank('first'))['evidence']
    item = edit(rows, 'Item.first', '@staticmethod\ndef first():\n    return 9')
    patch = json.loads(replacement.lower(json.dumps({'edits': [item]}), tmp_path, ['app.py'], rows))
    assert patch['edits'][0]['new'] == ('    @staticmethod\n    def first():\n        return 9\n').replace('\n', newline)
    item['new'] = 'def first():\n    return 9'
    with pytest.raises(ValueError, match='decorators'):
        replacement.lower(json.dumps({'edits': [item]}), tmp_path, ['app.py'], rows)


@pytest.mark.parametrize('protocol', ['baseline', 'function-replace'])
def test_feedback_protocol_reuses_current_hash_and_real_public_verification(tmp_path, monkeypatch, protocol):
    root, job, events, llm, raw = setup(tmp_path, monkeypatch, [])
    monkeypatch.setattr(worker, 'canonical_check', old.tentative.canonical_check)
    def chat(messages, tools=None):
        count = len(raw.messages); raw.messages.append(messages)
        data = json.loads(messages[1]['content'])
        if count and protocol == 'function-replace':
            row = data['fragments'][0]
            result = {'file': row['path'], 'symbol': row['symbol'], 'content_hash': row['content_hash'],
                      'new': 'def f():\n    return 3\n'}
        else:
            result = {'file': 'src/pkg/__init__.py', 'old': f'return {1 if count == 0 else 2}',
                      'new': f'return {2 if count == 0 else 3}'}
        return LLMResponse(content=json.dumps({'edits': [result]}), prompt_tokens=100, completion_tokens=100)
    monkeypatch.setattr(raw, 'chat', chat)
    job['edit_protocol'] = protocol
    result = worker.run_candidate(llm, job, events)
    assert result['public_checks']['final']['passed'] and len(raw.messages) == 2
    assert llm.metrics()['budget_accounted_tokens'] == 400
    assert 'return 3' in (root/'src/pkg/__init__.py').read_text()
    assert raw.messages[0][0]['content'] == worker.repair.patcher.SYMBOL_SYSTEM
    assert (raw.messages[1][0]['content'].startswith(replacement.SYSTEM)) == (protocol == 'function-replace')


@pytest.mark.parametrize('frame', ['{}', '```json\n{}\n```', '```\n{}\n```'])
def test_single_json_frame_preserves_exact_function_protocol(tmp_path, frame):
    rows = bundle(tmp_path)['evidence']
    content = json.dumps({'edits': [edit(rows)]})
    assert envelope.lower(frame.format(content), tmp_path, ['app.py'], rows) == replacement.lower(content, tmp_path, ['app.py'], rows)


@pytest.mark.parametrize('frame', ['explanation\n```json\n{}\n```', '```json\n{}\n```\nexplanation',
                                 '```json\n{}\n```\n```json\n{}\n```', '```python\n{}\n```'])
def test_json_frame_rejects_surrounding_text_multiple_blocks_and_other_languages(tmp_path, frame):
    rows = bundle(tmp_path)['evidence']
    content = json.dumps({'edits': [edit(rows)]})
    with pytest.raises(ValueError):
        envelope.lower(frame.format(content, content), tmp_path, ['app.py'], rows)
