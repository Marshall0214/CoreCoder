"""Conservative constructor-alias links for offline source diagnostics; never evaluate code."""

import ast
from collections import Counter

from .symbol_context import dependency_refs, dotted


def constructor_aliases(info):
    if info['tree'] is None:
        return {}
    writes = Counter()

    def walk(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            writes[node.name] += 1
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            writes[node.id] += 1
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for item in node.names:
                writes[item.asname or item.name.split('.')[0]] += 1
        for child in ast.iter_child_nodes(node):
            walk(child)

    for node in info['tree'].body:
        walk(node)
    result = {}
    for node in info['tree'].body:
        targets = node.targets if isinstance(node, ast.Assign) else ([node.target] if isinstance(node, ast.AnnAssign) else [])
        value = getattr(node, 'value', None)
        if len(targets) != 1 or not isinstance(targets[0], ast.Name) or not isinstance(value, ast.Call):
            continue
        alias, target = targets[0].id, dotted(value.func)
        symbol = info['symbols'].get(target)
        if (writes[alias] != 1 or writes[target] != 1 or symbol is None
                or not isinstance(symbol[2], ast.ClassDef)):
            continue
        result[alias] = {'target': target, 'binding_range': [node.lineno, node.end_lineno],
                         'kind': 'syntactic-constructor-alias'}
    return result


def linked_refs(info, start, end, symbol, aliases):
    refs = dependency_refs(info, start, end, symbol)
    if info['tree'] is not None:
        for node in ast.walk(info['tree']):
            if start <= getattr(node, 'lineno', 0) <= end:
                name = dotted(node)
                if name.split('.', 1)[0] in aliases:
                    refs.add(('', name))
    return refs


def resolve_link(info, target, aliases):
    alias, _, suffix = target.partition('.')
    binding = aliases.get(alias)
    resolved_target = '.'.join(filter(None, [binding['target'], suffix])) if binding else target
    names = [name for name in info['symbols'] if resolved_target == name or resolved_target.startswith(name + '.')]
    if not names:
        return None
    return {'symbol': max(names, key=len), 'reference': target,
            'alias': alias if binding else None, 'binding': binding}


def attribute_assignments(info, start, end):
    """Report attribute assignments in an analyzed seed; do not infer runtime types."""
    result = []
    if info['tree'] is None:
        return result
    for node in ast.walk(info['tree']):
        if not start <= getattr(node, 'lineno', 0) <= end:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else ([node.target] if isinstance(node, ast.AnnAssign) else [])
        if getattr(node, 'value', None) is None:
            continue
        for target in targets:
            if isinstance(target, ast.Attribute):
                result.append({'attribute': dotted(target), 'start_line': node.lineno, 'end_line': node.end_lineno,
                               'expression': ast.unparse(node.value)})
    return sorted(result, key=lambda row: (row['start_line'], row['attribute']))
