import hashlib

import pytest

from repairflow.issue_tools import READ_CHARS, ToolError, apply_patch, read_symbol


@pytest.fixture
def source(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'module.py').write_bytes(b'def f(x):\r\n    return x + 1\r\n')
    return workspace


def edit(old='return x + 1', new='return x + 2', file='module.py'):
    return {'edits': [{'file': file, 'old': old, 'new': new}]}


def test_exact_decorated_async_method_includes_signature_and_docstring(source):
    raw = b'class A:\n    @staticmethod\n    async def f(x):\n        "doc"\n        return x\n'
    (source / 'module.py').write_bytes(raw)
    row = read_symbol(source, ['module.py'], 'module.py', 'A.f')
    assert row['content'].startswith('    @staticmethod\n    async def f(x):')
    assert '"doc"' in row['content'] and row['complete_symbol'] and row['next_offset'] is None
    assert row['content_hash'] == hashlib.sha256(raw).hexdigest()


def test_read_preserves_crlf_bytes(source):
    row = read_symbol(source, ['module.py'], 'module.py', 'f')
    assert row['content'].encode() == (source / 'module.py').read_bytes()


@pytest.mark.parametrize('declaration,symbol,kind', [
    ('_ansi_reset_all = "\\033[0m"\r\n', '_ansi_reset_all', 'assignment'),
    ('LIMIT: int = 10\r\n', 'LIMIT', 'assignment'),
    ('LIMIT: int\r\n', 'LIMIT', 'assignment'),
    ('FIRST = SECOND = 10\r\n', 'SECOND', 'assignment'),
    ('FIRST, (SECOND, *REST) = (1, (2, 3))\r\n', 'REST', 'assignment'),
    ('from ._compat import strip_ansi\r\n', 'strip_ansi', 'import'),
    ('from ..helpers import clean as strip_ansi\r\n', 'strip_ansi', 'import'),
    ('import package.child\r\n', 'package', 'import'),
    ('import package.child as helper\r\n', 'helper', 'import'),
    ('from .helpers import (\r\n    clean as strip_ansi,\r\n    other,\r\n)\r\n', 'strip_ansi', 'import'),
])
def test_read_module_declarations_preserves_source_and_identifies_kind(source, declaration, symbol, kind):
    raw = ('# retained header\r\n' + declaration + '\r\ndef f(): pass\r\n').encode()
    (source / 'module.py').write_bytes(raw)
    row = read_symbol(source, ['module.py'], 'module.py', symbol)
    assert row['content'] == declaration and row['start_line'] == 2
    assert row['end_line'] == 1 + len(declaration.splitlines())
    assert row['kind'] == kind and row['resolution'] == 'static_declaration'
    assert row['complete_symbol'] and row['next_offset'] is None
    assert row['content_hash'] == hashlib.sha256(raw).hexdigest()
    if kind == 'assignment':
        assert row['value_present'] is (declaration != 'LIMIT: int\r\n')


def test_import_receipt_describes_binding_without_following_or_executing_it(source, tmp_path):
    marker = tmp_path / 'must-not-exist'
    raw = ('from ..private import clean as strip_ansi\n'
           f"VALUE = __import__('pathlib').Path({str(marker)!r}).write_text('executed')\n")
    (source / 'module.py').write_bytes(raw.encode('utf-8'))
    imported = read_symbol(source, ['module.py'], 'module.py', 'strip_ansi')
    assert imported['import_source'] == {'module': 'private', 'name': 'clean', 'level': 2, 'followed': False}
    assert imported['content'] == 'from ..private import clean as strip_ansi\n'
    assert read_symbol(source, ['module.py'], 'module.py', 'VALUE')['kind'] == 'assignment'
    assert not marker.exists()
    # A reported origin grants no read permission, even when that file exists locally.
    (source / 'private.py').write_text('SECRET = 123\n')
    with pytest.raises(ToolError) as error:
        read_symbol(source, ['module.py'], 'private.py', 'SECRET')
    assert error.value.record['code'] == 'path_not_allowed'


@pytest.mark.parametrize('declaration,symbol', [
    ('import package.child\n', 'package.child'),
    ('from helpers import original as alias\n', 'original'),
    ('from helpers import *\n', 'unknown_export'),
    ('globals()["DYNAMIC"] = 1\n', 'DYNAMIC'),
    ('values[(DYNAMIC := 0)] = 1\n', 'DYNAMIC'),
    ('class A:\n    LOCAL = 1\n', 'LOCAL'),
    ('def f():\n    LOCAL = 1\n', 'LOCAL'),
    ('def f():\n    from helpers import local\n', 'local'),
])
def test_unbound_or_unsupported_names_are_not_reported_as_module_bindings(source, declaration, symbol):
    (source / 'module.py').write_text(declaration, encoding='utf-8')
    with pytest.raises(ToolError) as error:
        read_symbol(source, ['module.py'], 'module.py', symbol)
    assert error.value.record['code'] == 'symbol_not_found'
    assert 'static declaration' in error.value.record['message']


@pytest.mark.parametrize('declaration', [
    'VALUE = 1\nVALUE = 2\n',
    'if condition:\n    VALUE = 1\nelse:\n    VALUE = 2\n',
    'try:\n    from first import VALUE\nexcept ImportError:\n    from second import VALUE\n',
    'match condition:\n    case 1:\n        VALUE = 1\n    case _:\n        VALUE = 2\n',
    'def VALUE(): pass\nVALUE = 1\n',
])
def test_multiple_static_bindings_are_ambiguous_without_runtime_guessing(source, declaration):
    (source / 'module.py').write_text(declaration, encoding='utf-8')
    with pytest.raises(ToolError) as error:
        read_symbol(source, ['module.py'], 'module.py', 'VALUE')
    row = error.value.record
    assert row['code'] == 'symbol_ambiguous'
    assert len(row['candidates']) == 2
    assert all(c['symbol'] == 'VALUE' and 'kind' in c for c in row['candidates'])


def test_module_binding_pages_and_stale_receipts_use_the_existing_edit_boundary(source, tmp_path):
    text = 'VALUE = "' + '码' * (READ_CHARS + 50) + '"\n'
    (source / 'module.py').write_bytes(text.encode('utf-8'))
    first = read_symbol(source, ['module.py'], 'module.py', 'VALUE')
    second = read_symbol(source, ['module.py'], 'module.py', 'VALUE', first['next_offset'])
    assert first['content'] + second['content'] == text and second['next_offset'] is None
    (source / 'module.py').write_bytes((text + '# changed\n').encode('utf-8'))
    with pytest.raises(ToolError) as error:
        apply_patch(source, ['module.py'], [first], edit('VALUE = "', 'OTHER = "'), tmp_path / 'staging')
    assert error.value.record['code'] == 'stale_source'


def test_binding_candidates_are_bounded_and_binding_evidence_can_authorize_exact_edits(source, tmp_path):
    (source / 'module.py').write_bytes(''.join(f'VALUE_{n} = {n}\n' for n in range(25)).encode('utf-8'))
    with pytest.raises(ToolError) as error:
        read_symbol(source, ['module.py'], 'module.py', 'missing')
    assert len(error.value.record['candidates']) == 20 and error.value.record['candidates_truncated']
    row = read_symbol(source, ['module.py'], 'module.py', 'VALUE_0')
    result = apply_patch(source, ['module.py'], [row], edit('VALUE_0 = 0\n', 'VALUE_0 = 10\n'), tmp_path / 'staging')
    assert result['changed_files'] == ['module.py']
    assert (source / 'module.py').read_text().startswith('VALUE_0 = 10\n')


def test_ambiguous_short_name_and_duplicate_qualified_definitions(source):
    (source / 'module.py').write_text('class A:\n def f(self): pass\nclass B:\n def f(self): pass\n')
    with pytest.raises(ToolError) as error:
        read_symbol(source, ['module.py'], 'module.py', 'f')
    assert error.value.record['code'] == 'symbol_ambiguous'
    assert [c['symbol'] for c in error.value.record['candidates']] == ['A.f', 'B.f']
    assert read_symbol(source, ['module.py'], 'module.py', 'B.f')['symbol'] == 'B.f'
    (source / 'module.py').write_text('def f(): pass\ndef f(): pass\n')
    with pytest.raises(ToolError, match='qualified'):
        read_symbol(source, ['module.py'], 'module.py', 'f')


def test_symbol_pagination_never_silently_discards_source(source):
    text = 'def f():\n    "' + '码' * (READ_CHARS + 50) + '"\n    return 1\n'
    (source / 'module.py').write_bytes(text.encode('utf-8'))
    first = read_symbol(source, ['module.py'], 'module.py', 'f')
    second = read_symbol(source, ['module.py'], 'module.py', 'f', first['next_offset'])
    assert first['content'] + second['content'] == text
    assert len(first['content']) == READ_CHARS and not first['complete_symbol']
    assert second['next_offset'] is None and not second['complete_symbol']


@pytest.mark.parametrize('path', ['../module.py', 'C:/secret.py', '/module.py', 'secret.py', 'a\\b.py'])
def test_path_boundary_before_read_or_write(source, path, tmp_path):
    with pytest.raises(ToolError) as error:
        read_symbol(source, ['module.py'], path, 'f')
    assert error.value.record['code'] == 'path_not_allowed'
    with pytest.raises(ToolError):
        apply_patch(source, ['module.py'], [], edit(file=path), tmp_path / 'staging')


@pytest.mark.parametrize('symbol,offset', [('f', -1), ('f', True), ('f', 999), ('', 0), ([], 0)])
def test_invalid_read_arguments(source, symbol, offset):
    with pytest.raises(ToolError):
        read_symbol(source, ['module.py'], 'module.py', symbol, offset)


@pytest.mark.parametrize('case,code', [('missing', 'anchor_not_found'), ('outside', 'anchor_not_supplied'),
                                    ('same', 'no_change'), ('syntax', 'syntax_error'), ('stale', 'stale_source'),
                                    ('unread', 'source_not_read')])
def test_typed_rejections_never_change_source(source, tmp_path, case, code):
    row = read_symbol(source, ['module.py'], 'module.py', 'f')
    args = edit()
    if case == 'missing':
        args = edit(old='return x + 77')
    elif case == 'outside':
        row['content'] = 'def f(x):\r\n'
    elif case == 'same':
        args = edit(new='return x + 1')
    elif case == 'syntax':
        args = edit(new='return (')
    elif case == 'stale':
        (source / 'module.py').write_bytes(b'def f(x):\n    return x + 1\n')
    before = (source / 'module.py').read_bytes()
    with pytest.raises(ToolError) as error:
        apply_patch(source, ['module.py'], [] if case == 'unread' else [row], args, tmp_path / 'staging')
    assert error.value.record['code'] == code
    assert error.value.record['retryable'] is True
    assert (source / 'module.py').read_bytes() == before


def test_multi_edit_syntax_failure_is_atomic(source, tmp_path):
    (source / 'other.py').write_text('def g():\n    return 1\n')
    allowed = ['module.py', 'other.py']
    evidence = [read_symbol(source, allowed, path, symbol) for path, symbol in [('module.py', 'f'), ('other.py', 'g')]]
    before = {name: (source / name).read_bytes() for name in allowed}
    args = {'edits': [*edit()['edits'], *edit('return 1', 'return (', 'other.py')['edits']]}
    with pytest.raises(ToolError) as error:
        apply_patch(source, allowed, evidence, args, tmp_path / 'staging')
    assert error.value.record['code'] == 'syntax_error'
    assert before == {name: (source / name).read_bytes() for name in allowed}


def test_ambiguous_anchor_is_distinct_from_missing_anchor(source, tmp_path):
    (source / 'module.py').write_text('def f():\n    return 1\ndef g():\n    return 1\n')
    evidence = [read_symbol(source, ['module.py'], 'module.py', 'f')]
    with pytest.raises(ToolError) as error:
        apply_patch(source, ['module.py'], evidence, edit('return 1', 'return 2'), tmp_path / 'staging')
    assert error.value.record['code'] == 'anchor_ambiguous' and error.value.record['matches'] == 2


def test_valid_patch_publishes_only_after_validation(source, tmp_path):
    row = read_symbol(source, ['module.py'], 'module.py', 'f')
    result = apply_patch(source, ['module.py'], [row], edit(), tmp_path / 'staging')
    assert result['changed_files'] == ['module.py'] and '+    return x + 2' in result['patch']
    assert b'return x + 2\r\n' in (source / 'module.py').read_bytes()
