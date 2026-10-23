"""Versioned Python symbol reads and typed, atomic edits for prepared Issues."""
import ast
import hashlib
import json
import shutil
from pathlib import Path

from evals.runner import changes, snapshot
from evals.schema import relative_path
from evals.symbol_context import apply_symbol_patch

READ_CHARS = 6000
FILE_BYTES = 2_000_000


class ToolError(ValueError):
    def __init__(self, code, message, *, retryable=True, next_action='read_symbol', **details):
        self.record = dict(code=code, message=message, retryable=retryable, next_action=next_action, **details)
        super().__init__(message)


def source_path(workspace, allowed, name):
    try:
        relative_path(name)
    except ValueError as exc:
        raise ToolError('path_not_allowed', 'Use an exact allowed relative path.', retryable=False) from exc
    root = Path(workspace).resolve()
    path = root / name
    if name not in allowed or not path.resolve().is_relative_to(root):
        raise ToolError('path_not_allowed', 'Path is outside the allowed source.', retryable=False)
    if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in (path, *path.parents)):
        raise ToolError('path_not_allowed', 'Linked paths are not supported.', retryable=False)
    if not path.is_file() or path.stat().st_size > FILE_BYTES:
        raise ToolError('source_unavailable', 'Source is missing or exceeds the static read limit.', retryable=False)
    return path


def symbol_nodes(tree, prefix=''):
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            name = prefix + node.name
            yield name, node
            yield from symbol_nodes(node, name + '.')
        else:
            # Include definitions under module/class conditionals without executing them.
            for field in ('body', 'orelse', 'finalbody'):
                body = getattr(node, field, None)
                if isinstance(body, list):
                    yield from symbol_nodes(ast.Module(body=body, type_ignores=[]), prefix)


def read_symbol(workspace, allowed, path, symbol, offset=0):
    if not isinstance(symbol, str) or not symbol or len(symbol) > 256 or type(offset) is not int or offset < 0:
        raise ToolError('invalid_arguments', 'Supply symbol and a nonnegative character offset.')
    raw = source_path(workspace, allowed, path).read_bytes()
    try:
        text = raw.decode('utf-8')
        nodes = list(symbol_nodes(ast.parse(text)))
    except (UnicodeError, SyntaxError) as exc:
        raise ToolError('source_parse_error', 'Source cannot be parsed as UTF-8 Python.', file=path) from exc
    matches = [(name, node) for name, node in nodes if name == symbol]
    if not matches:
        matches = [(name, node) for name, node in nodes if name.rsplit('.', 1)[-1] == symbol]
    if len(matches) != 1:
        raise ToolError('symbol_ambiguous' if matches else 'symbol_not_found',
                        'Choose a qualified symbol from the candidates.', file=path,
                        candidates=[{'symbol': name, 'line': node.lineno} for name, node in (matches or nodes)[:20]],
                        candidates_truncated=len(matches or nodes) > 20)
    name, node = matches[0]
    lines = text.splitlines(keepends=True)
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    content = ''.join(lines[start - 1:node.end_lineno])
    if offset >= len(content):
        raise ToolError('invalid_offset', 'Offset is outside the symbol; restart at zero.', file=path, symbol=name)
    fragment = content[offset:offset + READ_CHARS]
    next_offset = offset + len(fragment)
    return {'path': path, 'symbol': name, 'start_line': start, 'end_line': node.end_lineno,
            'symbol_range': [start, node.end_lineno], 'content': fragment,
            'content_hash': hashlib.sha256(raw).hexdigest(), 'offset': offset,
            'complete_symbol': offset == 0 and next_offset == len(content),
            'next_offset': next_offset if next_offset < len(content) else None,
            'reason': 'explicit_symbol_read'}


def apply_patch(workspace, allowed, evidence, arguments, staging):
    if not isinstance(arguments, dict) or set(arguments) != {'edits'}:
        raise ToolError('invalid_patch_schema', 'Expected exactly an edits array.', next_action='apply_patch')
    edits = arguments['edits']
    if not isinstance(edits, list) or not 1 <= len(edits) <= 20:
        raise ToolError('invalid_patch_schema', 'Supply 1 to 20 edits.', next_action='apply_patch')
    simulated = {}
    for edit in edits:
        if (not isinstance(edit, dict) or set(edit) != {'file', 'old', 'new'}
                or not all(isinstance(v, str) for v in edit.values()) or not edit['old']):
            raise ToolError('invalid_patch_schema', 'Each edit needs string file, nonempty old, and string new.',
                            next_action='apply_patch')
        name = edit['file']
        path = source_path(workspace, allowed, name)
        raw = path.read_bytes()
        version = hashlib.sha256(raw).hexdigest()
        receipts = [row for row in evidence if row['path'] == name]
        if not receipts:
            raise ToolError('source_not_read', 'Read the intended symbol before editing.', file=name)
        if any(row['content_hash'] != version for row in receipts):
            raise ToolError('stale_source', 'Source changed since reading; read it again.', file=name)
        if edit['old'] == edit['new']:
            raise ToolError('no_change', 'Old and new must differ.', file=name, next_action='apply_patch')
        source = simulated.get(name, raw.decode('utf-8'))
        count = source.count(edit['old'])
        if count != 1:
            raise ToolError('anchor_not_found' if count == 0 else 'anchor_ambiguous',
                            'Old text must occur exactly once in current source.', file=name, matches=count)
        if not any(edit['old'] in row['content'] for row in receipts):
            raise ToolError('anchor_not_supplied', 'Anchor is outside the supplied fragments; read the symbol.', file=name)
        simulated[name] = source.replace(edit['old'], edit['new'], 1)
    # Reuse the established evidence/unique-anchor implementation in a disposable copy.
    shutil.copytree(workspace, staging)
    apply_symbol_patch(json.dumps(arguments), staging, allowed, evidence)
    try:
        for name in simulated:
            compile((staging / name).read_bytes(), name, 'exec')
    except SyntaxError as exc:
        raise ToolError('syntax_error', 'Patch was not published: ' + exc.msg, file=name,
                        line=exc.lineno, next_action='apply_patch') from exc
    changed, patch = changes(snapshot(workspace), snapshot(staging))
    if not changed:
        raise ToolError('no_change', 'Combined edits have no net change.', next_action='apply_patch')
    for name in changed:
        (workspace / name).write_bytes((staging / name).read_bytes())
    return {'status': 'completed', 'changed_files': changed, 'patch': patch}
