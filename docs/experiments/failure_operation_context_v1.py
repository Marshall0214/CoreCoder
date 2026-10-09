"""Reselect current source using failed public operations and bounded reverse callers."""
import ast
import re
from pathlib import Path

from docs.experiments import public_feedback_v2 as previous
from evals.symbol_context import dependency_refs, module_name

REFRESH = previous.refresh_seeds


def select(workspace, allowed, seeds, test_code, stderr):
    workspace = Path(workspace).resolve()
    base = REFRESH(workspace, allowed, seeds)
    index = previous.baseline.functions.FunctionIndex(workspace, allowed)
    index.refresh()
    chunks = {(c.path, index.names[(c.path, c.start_line, c.end_line)]): c for c in index.chunks}
    tree = ast.parse(test_code)
    frames = [(int(line), name.strip()) for path, line, name in re.findall(
        r'File "([^"]+)", line (\d+), in ([^\n]+)', stderr)
        if Path(path).name == 'test_admission.py']
    scopes = []
    for line, name in frames:
        candidates = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.name == name and n.lineno <= line <= n.end_lineno]
        if candidates:
            scopes.append((min(candidates, key=lambda n: n.end_lineno - n.lineno), line))
    aliases = {a.asname or a.name: (a.name, n.module or '') for n in ast.walk(tree)
               if isinstance(n, ast.ImportFrom) for a in n.names}
    classes = {}
    for path, info in index.parsed.items():
        for symbol, (_, _, node) in info['symbols'].items():
            if isinstance(node, ast.ClassDef):
                classes.setdefault(symbol.rsplit('.', 1)[-1], []).append((path, symbol))
    priorities = {}
    reasons = {}
    base_keys = {(r['path'], r['symbol']) for r in base['evidence']}

    def promote(key, priority, reason):
        if key in chunks and key not in base_keys and priority > priorities.get(key, 0):
            priorities[key], reasons[key] = priority, reason

    for scope, line in scopes:
        bindings = {}
        assignments = [n for n in ast.walk(scope) if isinstance(n, ast.Assign) and n.lineno <= line]
        # A repeatedly rebound local is ambiguous, rather than a reliable type witness.
        counts = {}
        for node in assignments:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    counts[target.id] = counts.get(target.id, 0) + 1
        for node in assignments:
            fn = node.value.func if isinstance(node.value, ast.Call) else None
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ''
            imported, module = aliases.get(name, (name, ''))
            owners = [owner for owner in classes.get(imported, [])
                      if not module or module_name(owner[0]) == module or module_name(owner[0]).startswith(module + '.')]
            if len(owners) == 1:
                for target in node.targets:
                    if isinstance(target, ast.Name) and counts[target.id] == 1:
                        bindings[target.id] = owners[0]
        expressions = [n for n in ast.walk(scope) if isinstance(n, ast.Call)
                       and n.lineno <= line <= n.end_lineno]

        def method(value, magic, type_bindings=bindings):
            if isinstance(value, ast.Name) and value.id in type_bindings:
                path, owner = type_bindings[value.id]
                promote((path, owner + '.' + magic), 200, 'failed_public_operation:' + magic)

        for expression in expressions:
            for node in ast.walk(expression):
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                        node.func.id if isinstance(node.func, ast.Name) else '')
                    if name in ('assertIn', 'assertNotIn') and len(node.args) >= 2:
                        method(node.args[1], '__contains__')
                    if isinstance(node.func, ast.Name) and node.args:
                        magic = {'reversed': '__reversed__', 'len': '__len__', 'bool': '__bool__'}.get(name)
                        if magic:
                            method(node.args[0], magic)
                elif isinstance(node, ast.Compare):
                    for op, value in zip(node.ops, node.comparators):
                        if isinstance(op, (ast.In, ast.NotIn)):
                            method(value, '__contains__')
        # Derive lexical operation cues from flags actually used in the failed test.
        # Incoming edges are static same-owner/import references, never task-specific names.
        flags = {n.value.lstrip('-').split('=')[0].replace('-', '_') for n in ast.walk(scope)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith('--')
                 and n.lineno <= line}
        for key, chunk in chunks.items():
            if not flags.intersection(key[1].rsplit('.', 1)[-1].split('_')):
                continue
            refs = {(path or key[0], symbol) for path, symbol in dependency_refs(
                index.parsed[key[0]], chunk.start_line, chunk.end_line, key[1])}
            if refs & base_keys:
                promote(key, 150, 'failed_public_flag_reverse_caller')
    if not priorities:
        base['metadata'].update(operation_candidates=[], fallback='unchanged_refreshed_seeds')
        return base
    scored = {(r['path'], r['symbol']): r.get('score', 0) for r in base['evidence']}
    old = {(r['path'], r['symbol']): r['content'] for r in seeds}
    edited = [(r['path'], r['symbol']) for r in base['evidence']
              if old.get((r['path'], r['symbol'])) != r['content']]
    keys = sorted(priorities, key=lambda k: (-priorities[k], k))
    keys += [k for k in edited if k not in keys]
    keys += [(r['path'], r['symbol']) for r in base['evidence'] if (r['path'], r['symbol']) not in keys]
    packed = previous.baseline.functions.pack(index, [(scored.get(k, 0), chunks[k]) for k in keys])
    for row in packed['evidence']:
        key = (row['path'], row['symbol'])
        row['reason'] = reasons.get(key, next((r['reason'] for r in base['evidence']
                                             if (r['path'], r['symbol']) == key), row['reason']))
    packed['metadata']['operation_candidates'] = [{'path': k[0], 'symbol': k[1], 'reason': reasons[k]}
                                                 for k in sorted(priorities)]
    packed['metadata']['failed_public_frames'] = frames
    packed['metadata']['edited_seed_symbols'] = [list(k) for k in edited]
    previous.repair.validate_evidence(workspace, allowed, packed['evidence'])
    return packed
