"""Reselect complete current functions from public traceback/API evidence only."""
import ast
import re
from pathlib import Path

from docs.experiments import public_feedback_v2 as policy


def context(workspace, allowed, seeds, test_code, stderr, logged_workspace=None):
    workspace = Path(workspace).resolve()
    logged_workspace = Path(logged_workspace or workspace).resolve()
    policy.repair.validate_evidence(workspace, allowed, seeds)
    index = policy.baseline.functions.FunctionIndex(workspace, allowed)
    index.refresh()
    chunks = {(c.path, index.names[(c.path, c.start_line, c.end_line)]): c for c in index.chunks}
    priorities, reasons = {}, {}

    def promote(key, priority, reason):
        if key in chunks and priority > priorities.get(key, 0):
            priorities[key], reasons[key] = priority, reason

    frames = re.findall(r'File "([^"]+)", line (\d+), in [^\n]+', stderr)
    for order, (path, line) in enumerate(frames):
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(logged_workspace):
            continue
        relative = resolved.relative_to(logged_workspace).as_posix()
        if relative not in allowed:
            continue
        containing = [(key, c) for key, c in chunks.items() if key[0] == relative and c.start_line <= int(line) <= c.end_line]
        if containing:
            key, _ = min(containing, key=lambda pair: pair[1].end_line - pair[1].start_line)
            promote(key, 300 + order, 'public_failure_frame')

    classes = {}
    for path, info in index.parsed.items():
        for symbol, (_, _, node) in info['symbols'].items():
            if isinstance(node, ast.ClassDef):
                classes.setdefault(symbol.rsplit('.', 1)[-1], []).append((path, symbol))

    def constructor(node):
        name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ''
        owners = classes.get(name, [])
        return owners[0] if len(owners) == 1 else None

    tree = ast.parse(test_code)
    # Keep bindings local to each public test/helper, never execute those helpers.
    scopes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for scope in scopes:
        bindings = {}
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                owner = constructor(node.value.func)
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if owner:
                            bindings[target.id] = owner
                        else:
                            bindings.pop(target.id, None)
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ''
            # Construction and helper calls alone are not failure evidence. Do not
            # crowd out repair functions with CliRunner/test setup constructors.
            implicit = {'assertIn': '__contains__', 'assertNotIn': '__contains__'}
            arg = node.args[1] if name in implicit and len(node.args) > 1 else None
            if isinstance(arg, ast.Name) and arg.id in bindings:
                path, cls = bindings[arg.id]
                promote((path, cls + '.' + implicit[name]), 250, 'public_membership_contract')
    seed_scores = {(r['path'], r['symbol']): r.get('score', 0) for r in seeds}
    chosen = [key for key in chunks if key in priorities or key in seed_scores]
    chosen.sort(key=lambda k: (-priorities.get(k, 0), -seed_scores.get(k, 0), k))
    result = policy.baseline.functions.pack(index, [(seed_scores.get(k, 0), chunks[k]) for k in chosen])
    result['metadata']['selection'] = [{'path': r['path'], 'symbol': r['symbol'],
                                       'reason': reasons.get((r['path'], r['symbol']), 'refreshed_seed')}
                                      for r in result['evidence']]
    policy.repair.validate_evidence(workspace, allowed, result['evidence'])
    return result
