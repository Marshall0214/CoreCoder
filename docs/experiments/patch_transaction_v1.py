"""Opt-in patch staging and validation. No changes to the frozen repair engine."""

import ast
import json
import shutil
from collections import Counter
from pathlib import Path

from evals.process import run_process, test_environment
from evals.symbol_context import apply_symbol_patch

BOOT = """import importlib, json, pathlib, sys
source = pathlib.Path(sys.argv[1]).resolve()
specs = json.loads(sys.argv[2])
for spec in specs:
    sys.path.insert(0, str(source / spec['root']))
    module = importlib.import_module(spec['module'])
    assert pathlib.Path(module.__file__).resolve() == source / spec['path'], 'Wrong module origin'
"""


def files(root):
    """Exact regular-file snapshot; links are unsupported by this experiment."""
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('Linked source trees are unsupported')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def definitions(source):
    """Count concrete declarations in the same lexical execution block.

    Ignore typing overload declarations; property accessors are separate roles.
    Conditional branches have separate keys. This is a conservative structural
    diagnostic, not a general proof about dynamic Python name binding.
    """
    tree = ast.parse(source)
    typing_names, overload_names = set(), set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            typing_names.update(a.asname or a.name for a in node.names
                                if a.name in {'typing', 'typing_extensions'})
        elif isinstance(node, ast.ImportFrom) and node.module in {'typing', 'typing_extensions'}:
            overload_names.update(a.asname or a.name for a in node.names if a.name == 'overload')
    counts = Counter()

    def overload(decorator):
        return ((isinstance(decorator, ast.Name) and decorator.id in overload_names)
                or (isinstance(decorator, ast.Attribute) and decorator.attr == 'overload'
                    and isinstance(decorator.value, ast.Name) and decorator.value.id in typing_names))

    def walk(body, scope):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                role = type(node).__name__
                if not isinstance(node, ast.ClassDef):
                    if any(overload(d) for d in node.decorator_list):
                        continue
                    for decorator in node.decorator_list:
                        if (isinstance(decorator, ast.Attribute) and decorator.attr in {'setter', 'deleter'}
                                and isinstance(decorator.value, ast.Name) and decorator.value.id == node.name):
                            role = decorator.attr
                counts[(scope, node.name, role)] += 1
                walk(node.body, scope + '/' + node.name)
            else:
                # Group declarations only within the same branch, not across if/else.
                identity = type(node).__name__ + ':' + ast.dump(node, include_attributes=False).split('body=')[0]
                for field, value in ast.iter_fields(node):
                    if isinstance(value, list) and value and all(isinstance(v, ast.stmt) for v in value):
                        walk(value, scope + '/' + identity + '/' + field)

    walk(tree.body, '<module>')
    return counts


def added_duplicates(before, after):
    old, new = definitions(before), definitions(after)
    return [{'scope': key[0], 'name': key[1], 'role': key[2], 'before': old[key], 'after': count}
            for key, count in sorted(new.items()) if count > 1 and count > old[key]]


def _write(path, content):
    path.write_bytes(content)


def transact(content, workspace, allowed_files, evidence, output, python, imports, timeout=10):
    """Stage, validate, then write changed files, rolling back write exceptions.

    Caller must exclusively own the disposable workspace. This is not a filesystem
    lock, crash-safe multi-file commit, semantic verifier, or OS execution sandbox.
    Import specifications belong to the caller, never to model output.
    """
    workspace, output = Path(workspace).resolve(), Path(output).resolve()
    if output.is_relative_to(workspace) or workspace.is_relative_to(output):
        raise ValueError('Transaction output must be outside the workspace')
    if not imports or type(timeout) is not int or timeout <= 0:
        raise ValueError('At least one import check and positive timeout are required')
    for spec in imports:
        if set(spec) != {'module', 'root', 'path'} or not spec['module']:
            raise ValueError('Invalid caller import specification')
        for key in ('root', 'path'):
            value = Path(spec[key])
            if value.is_absolute() or '..' in value.parts:
                raise ValueError('Import paths must stay in the staged workspace')
        if not (workspace / spec['path']).is_file() or not (workspace / spec['root']).is_dir():
            raise ValueError('Missing import source')
    before = files(workspace)
    output.mkdir(parents=True, exist_ok=False)
    stage = output / 'stage'
    shutil.copytree(workspace, stage)
    result = {'accepted': False, 'committed': False, 'reason': None,
              'changed_files': [], 'duplicates': [], 'import': None}

    def finish(reason):
        result['reason'] = reason
        result['original_unchanged'] = files(workspace) == before
        (output / 'transaction.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result

    try:
        changed = apply_symbol_patch(content, stage, allowed_files, evidence)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        result['error'] = str(exc)
        return finish('invalid_patch')
    candidate = files(stage)
    result['changed_files'] = changed
    try:
        for name in changed:
            if name.endswith('.py'):
                compile(candidate[name], name, 'exec')
                result['duplicates'].extend(dict(row, file=name)
                                            for row in added_duplicates(before[name], candidate[name]))
    except (SyntaxError, ValueError) as exc:
        result['error'] = str(exc)
        return finish('invalid_python')
    if result['duplicates']:
        return finish('added_duplicate_definitions')
    # Execute a separate copy; detect any persistent file mutation by module loading.
    smoke = output / 'import-source'
    shutil.copytree(stage, smoke)
    result['import'] = run_process(
        [str(python), '-I', '-B', '-c', BOOT, str(smoke), json.dumps(imports)],
        smoke, timeout, output / 'import.stdout.txt', output / 'import.stderr.txt', test_environment(smoke))
    if files(smoke) != candidate:
        return finish('import_mutated_source')
    if result['import']['timed_out'] or result['import']['returncode'] != 0:
        return finish('import_failed')
    if files(workspace) != before:
        return finish('source_changed')
    written = []
    try:
        for name in changed:
            written.append(name)
            _write(workspace / name, candidate[name])
    except OSError as exc:
        # Bypass the injectable commit writer when restoring original bytes.
        for name in reversed(written):
            (workspace / name).write_bytes(before[name])
        result['error'] = str(exc)
        return finish('commit_failed')
    result.update(accepted=True, committed=True)
    return finish('committed')
