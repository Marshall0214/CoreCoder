"""Supplement public API context with named state producers and referenced converters."""
import ast
import re

from docs.experiments import public_api_context_v1 as previous
from docs.experiments.function_index_audit_v1 import FunctionIndex
from docs.experiments.function_index_repair_v1 import validate_evidence
from evals.symbol_context import dependency_refs


def retrieve(workspace, allowed, description, public_code=''):
    baseline = previous.retrieve(workspace, allowed, description, public_code)
    index = FunctionIndex(workspace, allowed)
    index.refresh()
    words = set(re.findall(r'[A-Za-z_]\w*', description))
    primary = [r for r in baseline['evidence'] if r['reason'] == 'public_factory_class_method']
    additions = []

    def fragment(path, symbol, start, end, reason):
        info = index.parsed[path]
        begin, finish, node = info['symbols'][symbol]
        return {'path': path, 'symbol': symbol, 'start_line': start, 'end_line': end,
                'content': ''.join(info['lines'][start - 1:end]), 'content_hash': info['hash'],
                'symbol_range': [begin, finish], 'complete_symbol': start == begin and end == finish,
                'signature': symbol + '(' + ast.unparse(node.args) + ')', 'reason': reason, 'score': 0}

    for row in primary:
        path, symbol = row['path'], row['symbol']
        if '.' not in symbol:
            continue
        info = index.parsed[path]
        node = info['symbols'][symbol][2]
        fields = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
                  and isinstance(n.value, ast.Name) and n.value.id == 'self'} & words
        ctor = symbol.rsplit('.', 1)[0] + '.__init__'
        if not fields or ctor not in info['symbols']:
            continue
        constructor = info['symbols'][ctor][2]
        writers = [statement for statement in constructor.body if any(
            isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store) and n.attr in fields
            and isinstance(n.value, ast.Name) and n.value.id == 'self' for n in ast.walk(statement))]
        if not writers:
            continue
        first = constructor.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            first = constructor.body[1] if len(constructor.body) > 1 else first
        start, end = first.lineno, max(s.end_lineno for s in writers)
        additions.append(fragment(path, ctor, start, end, 'named_state_initialization_prefix'))
        # Inspect runtime calls: annotation-only base types are not conversion evidence.
        calls = [n for n in ast.walk(constructor) if isinstance(n, ast.Call)
                 and start <= n.lineno <= end]
        runtime_info = dict(info, tree=ast.Module(body=calls, type_ignores=[]))
        for other, target in sorted(dependency_refs(runtime_info, start, end, ctor)):
            other = other or path
            target_info = index.parsed.get(other)
            if not target_info or target not in target_info['symbols']:
                continue
            if not isinstance(target_info['symbols'][target][2], ast.ClassDef):
                continue
            converter = target + '.convert'
            if converter in target_info['symbols']:
                begin, finish, _ = target_info['symbols'][converter]
                additions.append(fragment(other, converter, begin, finish, 'referenced_type_converter'))

    # Prefer inheritance-chain methods over unrelated global utilities when space is tight.
    remainder = sorted([r for r in baseline['evidence'] if r not in primary],
                       key=lambda r: ('.' not in r['symbol'],
                                      r['reason'] != 'public_api_static_dependency'))
    evidence, omitted, used = [], [], 0
    for row in [*primary, *additions, *remainder]:
        if any(r['path'] == row['path'] and r['start_line'] <= row['end_line']
               and row['start_line'] <= r['end_line'] for r in evidence):
            continue
        if len(evidence) == 5 or used + len(row['content']) > 6000:
            omitted.append({'path': row['path'], 'symbol': row['symbol'], 'reason': 'budget'})
            continue
        evidence.append(row)
        used += len(row['content'])
    validate_evidence(workspace, allowed, evidence)
    return {'evidence': evidence, 'metadata': {'policy': 'state-type-context-v1', 'chars': used,
            'max_chars': 6000, 'max_fragments': 5, 'discarded': omitted,
            'public_api_owners': baseline['metadata']['public_api_owners'],
            'source': 'description identifiers, public API AST and allowed original source only',
            'requested_additions': [{'path': r['path'], 'symbol': r['symbol']} for r in additions]}}
