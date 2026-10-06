import hashlib
import json

import pytest

from docs.experiments.definition_read_v1 import DefinitionReadTool
from evals.staged_repair import read_fragments


def tool(tmp_path, text):
    (tmp_path / 'entry.py').write_bytes(text.encode())
    return DefinitionReadTool(tmp_path, ['entry.py'])


def test_complete_decorated_definition_preserves_docs_and_receipt(tmp_path):
    text = '@decorate\ndef prompt():\n    """contract"""\n    return 1\nother = 2\n'
    reader = tool(tmp_path, text)
    result = json.loads(reader.execute('entry.py', 'prompt'))
    assert result['definition_range'] == result['shown_range'] == [1, 4]
    assert result['complete_symbol'] and result['next_offset'] is None and result['missing_ranges'] == []
    assert 'contract' in result['content'] and 'other' not in result['content']
    rows = read_fragments(tmp_path, ['entry.py'], reader.fragment_receipts)
    assert rows[0]['end_line'] == 4 and rows[0]['content_hash'] == hashlib.sha256(text.encode()).hexdigest()


def test_long_definition_continuation_does_not_claim_whole_symbol_complete(tmp_path):
    reader = tool(tmp_path, 'def prompt():\n' + '    x = 1\n' * 130)
    first = json.loads(reader.execute('entry.py', 'prompt'))
    assert first['shown_range'] == [1, 120] and first['next_offset'] == 121
    assert not first['complete_symbol'] and first['limit_reason'] == 'line_cap'
    second = json.loads(reader.execute('entry.py', 'prompt', first['next_offset']))
    assert second['shown_range'] == [121, 131] and second['next_offset'] is None
    assert not second['complete_symbol'] and second['missing_ranges'] == [[1, 120]]


def test_character_cap_counts_entire_escaped_json_and_keeps_whole_lines(tmp_path):
    reader = tool(tmp_path, 'def prompt():\n' + ('    x = ' + repr('"\\' * 180) + '\n') * 20)
    response = reader.execute('entry.py', 'prompt')
    result = json.loads(response)
    assert len(response) <= 6000 and result['limit_reason'] == 'character_cap'
    assert result['shown_range'][1] < 21
    assert read_fragments(tmp_path, ['entry.py'], reader.fragment_receipts)


def test_unreadable_long_line_is_not_forged_or_skipped(tmp_path):
    reader = tool(tmp_path, 'def prompt(' + 'argument,' * 1000 + '):\n    pass\n')
    result = json.loads(reader.execute('entry.py', 'prompt'))
    assert result['status'] == 'blocked' and result['next_offset'] == 1
    assert result['shown_range'] is None and reader.fragment_receipts == []


def test_qualified_nested_and_async_names_do_not_match_unrelated_definitions(tmp_path):
    reader = tool(tmp_path, 'class Context:\n    async def invoke(self):\n        pass\n'
                  'def outer():\n    def inner():\n        pass\n    return inner\n')
    assert json.loads(reader.execute('entry.py', 'Context.invoke'))['definition_range'] == [2, 3]
    assert json.loads(reader.execute('entry.py', 'outer.inner'))['definition_range'] == [5, 6]
    assert json.loads(reader.execute('entry.py', 'invoke'))['error'] == 'symbol_not_found'


def test_overload_stubs_resolve_only_unique_implementation(tmp_path):
    reader = tool(tmp_path, 'import typing as t\nfrom typing import overload\n@t.overload\ndef prompt(x: int): ...\n'
                  '@overload\ndef prompt(x: str): ...\ndef prompt(x):\n    return x\n')
    result = json.loads(reader.execute('entry.py', 'prompt'))
    assert result['definition_range'] == [7, 8] and result['overload_count'] == 2


@pytest.mark.parametrize('source,error', [('from typing import overload\n@overload\ndef prompt(x): ...\n', 'implementation_not_found'),
                                         ('def prompt(): pass\ndef prompt(): pass\n', 'ambiguous_definition'),
                                         ('def prompt(\n', 'source_syntax_error')])
def test_ambiguous_or_invalid_source_is_not_guessed(tmp_path, source, error):
    assert json.loads(tool(tmp_path, source).execute('entry.py', 'prompt'))['error'] == error


@pytest.mark.parametrize('path,offset', [('../entry.py', None), ('not-allowed.py', None), ('entry.py', 0),
                                       ('entry.py', True), ('entry.py', 99)])
def test_scope_and_offsets_are_enforced(tmp_path, path, offset):
    result = json.loads(tool(tmp_path, 'def prompt():\n    pass\n').execute(path, 'prompt', offset))
    assert result['status'] == 'error'


def test_unicode_crlf_is_preserved_in_source_version_and_receipts(tmp_path):
    reader = tool(tmp_path, 'def prompt():\r\n    """中文契约"""\r\n    return "中文"\r\n')
    result = json.loads(reader.execute('entry.py', 'prompt'))
    assert result['complete_symbol'] and '中文契约' in result['content']
    assert read_fragments(tmp_path, ['entry.py'], reader.fragment_receipts)[0]['end_line'] == 3


def test_unrelated_overload_named_decorator_is_not_treated_as_typing_stub(tmp_path):
    result = json.loads(tool(tmp_path, '@custom.overload\ndef prompt():\n    return 1\n').execute('entry.py', 'prompt'))
    assert result['complete_symbol'] and result['overload_count'] == 0


def test_source_change_during_read_cannot_authorize_fragment(tmp_path, monkeypatch):
    reader = tool(tmp_path, 'def prompt():\n    return 1\n')
    from pathlib import Path

    original = Path.read_bytes
    calls = 0

    def changed(path):
        nonlocal calls
        raw = original(path)
        calls += 1
        return raw if calls == 1 else b'changed'

    monkeypatch.setattr(Path, 'read_bytes', changed)
    result = json.loads(reader.execute('entry.py', 'prompt'))
    assert result['error'] == 'source_changed_during_read' and reader.fragment_receipts == []
