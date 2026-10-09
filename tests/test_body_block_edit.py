import ast
import hashlib
import json
from types import SimpleNamespace

import pytest

from docs.experiments import body_block_edit_v1 as editor
from evals.symbol_context import apply_symbol_patch


@pytest.fixture
def source(tmp_path):
    code = '''class Worker:
    @staticmethod
    def fix(value=1):
        """Keep this documentation exactly."""
        return value + 1

async def other(value):
    return value
'''
    path = tmp_path / 'example.py'
    path.write_text(code, encoding='utf-8', newline='')
    version = hashlib.sha256(path.read_bytes()).hexdigest()
    lines = code.splitlines(keepends=True)
    nodes = editor.replacement.base.declarations(ast.parse(code))
    rows = []
    for symbol, found in nodes.items():
        n = found[0]
        start = min([n.lineno] + [d.lineno for d in n.decorator_list])
        rows.append({'path': 'example.py', 'symbol': symbol, 'start_line': start, 'end_line': n.end_lineno,
                     'content': ''.join(lines[start-1:n.end_lineno]), 'content_hash': version})
    return tmp_path, path, rows


def payload(catalog, body='return value * 2', symbol='Worker.fix'):
    key = next(k for k, b in catalog.items() if b['symbol'] == symbol)
    return json.dumps({'edits': [{'block_id': key, 'new_body': body}]})


def test_body_edit_preserves_docstring_signature_decorator_and_indentation(source):
    root, path, rows = source
    catalog = editor.blocks(root, ['example.py'], rows)
    patch = editor.lower(payload(catalog), root, ['example.py'], rows, catalog)
    apply_symbol_patch(patch, root, ['example.py'], rows)
    text = path.read_text()
    assert '@staticmethod\n    def fix(value=1):\n        """Keep this documentation exactly."""' in text
    assert '        return value * 2' in text
    namespace = {}
    exec(compile(text, str(path), 'exec'), namespace)  # noqa: S102 - execute only the fixed local fixture
    assert namespace['Worker'].fix(3) == 6


def test_async_body_replacement_preserves_async_header(source):
    root, _, rows = source
    catalog = editor.blocks(root, ['example.py'], rows)
    patch = editor.lower(payload(catalog, 'return value + 2', 'other'), root, ['example.py'], rows, catalog)
    function = ast.parse(json.loads(patch)['edits'][0]['new']).body[0]
    assert isinstance(function, ast.AsyncFunctionDef) and function.name == 'other'


@pytest.mark.parametrize('body', ['"""Repeated documentation"""\nreturn value', 'def fix(value):\n    return value'])
def test_repeated_docstring_or_signature_is_rejected_without_writes(source, body):
    root, path, rows = source
    original = path.read_bytes()
    catalog = editor.blocks(root, ['example.py'], rows)
    with pytest.raises(ValueError, match='Do not repeat'):
        editor.lower(payload(catalog, body), root, ['example.py'], rows, catalog)
    assert path.read_bytes() == original


def test_stale_file_version_is_rejected(source):
    root, path, rows = source
    catalog = editor.blocks(root, ['example.py'], rows)
    path.write_text(path.read_text() + '\nchanged = True\n', encoding='utf-8')
    with pytest.raises(ValueError, match='version'):
        editor.lower(payload(catalog), root, ['example.py'], rows, catalog)


def test_unknown_and_duplicate_blocks_are_rejected(source):
    root, _, rows = source
    catalog = editor.blocks(root, ['example.py'], rows)
    with pytest.raises(ValueError, match='Unknown'):
        editor.lower('{"edits":[{"block_id":"missing","new_body":"pass"}]}', root, ['example.py'], rows, catalog)
    data = json.loads(payload(catalog))
    data['edits'] *= 2
    with pytest.raises(ValueError, match='duplicate'):
        editor.lower(json.dumps(data), root, ['example.py'], rows, catalog)


def test_partial_function_is_not_advertised_as_editable(source):
    root, _, rows = source
    rows[0] = dict(rows[0], start_line=rows[0]['start_line'] + 1, content=''.join(rows[0]['content'].splitlines(True)[1:]))
    catalog = editor.blocks(root, ['example.py'], rows)
    assert all(b['symbol'] != 'Worker.fix' for b in catalog.values())


def test_multiple_body_edits_share_the_original_file_version(source):
    root, path, rows = source
    catalog = editor.blocks(root, ['example.py'], rows)
    entries = [json.loads(payload(catalog, 'return value * 3', symbol))['edits'][0] for symbol in ('Worker.fix', 'other')]
    patch = editor.lower(json.dumps({'edits': entries}), root, ['example.py'], rows, catalog)
    apply_symbol_patch(patch, root, ['example.py'], rows)
    assert path.read_text().count('return value * 3') == 2


def test_crlf_is_preserved(source):
    root, path, rows = source
    path.write_bytes(path.read_bytes().replace(b'\n', b'\r\n'))
    version = hashlib.sha256(path.read_bytes()).hexdigest()
    rows = [dict(r, content=r['content'].replace('\n', '\r\n'), content_hash=version) for r in rows]
    catalog = editor.blocks(root, ['example.py'], rows)
    patch = editor.lower(payload(catalog), root, ['example.py'], rows, catalog)
    apply_symbol_patch(patch, root, ['example.py'], rows)
    assert b'\r\n' in path.read_bytes() and b'\n' not in path.read_bytes().replace(b'\r\n', b'')


def test_feedback_override_restores_frozen_request_after_exception(monkeypatch):
    original = editor.previous.request
    def fail(*args):
        raise RuntimeError('failure')
    monkeypatch.setattr(editor.guarded, 'run_candidate', fail)
    with pytest.raises(RuntimeError):
        editor.run_candidate(None, {}, None)
    assert editor.previous.request is original


def test_invalid_body_never_changes_the_workspace(source):
    root, path, rows = source
    original = path.read_bytes()
    catalog = editor.blocks(root, ['example.py'], rows)
    with pytest.raises(SyntaxError):
        editor.lower(payload(catalog, 'return ('), root, ['example.py'], rows, catalog)
    assert path.read_bytes() == original


def test_initial_request_uses_the_original_protocol(monkeypatch):
    calls = []
    def request(*args):
        calls.append(args[5])
        return {'status': 'completed'}
    monkeypatch.setattr(editor.previous, 'request', request)
    def candidate(llm, job, events):
        return editor.previous.request(llm, None, job, [], None, 'initial')
    monkeypatch.setattr(editor.guarded, 'run_candidate', candidate)
    editor.run_candidate(SimpleNamespace(), {}, None)
    assert calls == ['initial']
