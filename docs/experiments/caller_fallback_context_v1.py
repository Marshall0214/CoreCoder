"""Reserve bounded context for callers and effective self-method dispatch."""
import ast

from docs.experiments import state_type_context_v1 as previous
from docs.experiments.function_index_audit_v1 import FunctionIndex
from docs.experiments.function_index_repair_v1 import validate_evidence


def retrieve(workspace, allowed, description, public_code=''):
    baseline = previous.retrieve(workspace, allowed, description, public_code)
    index = FunctionIndex(workspace, allowed)
    index.refresh()
    primary = [r for r in baseline['evidence'] if r['reason'] == 'public_factory_class_method']
    additions = []

    def bases(path, owner, seen=None):
        seen = set() if seen is None else seen
        if (path, owner) in seen:
            return []
        seen.add((path, owner))
        info = index.parsed.get(path)
        entry = info and info['symbols'].get(owner)
        if not entry or not isinstance(entry[2], ast.ClassDef):
            return []
        result = [(path, owner)]
        for base in entry[2].bases:
            if isinstance(base, ast.Name):
                p, n = info['bindings'].get(base.id, (path, base.id))
                result.extend(bases(p, n, seen))
        return result

    def fragment(path, symbol, reason):
        info = index.parsed[path]
        start, end, node = info['symbols'][symbol]
        begin = start
        doc = node.body[0] if node.body else None
        if (isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant)
                and isinstance(doc.value.value, str) and len(node.body) > 1):
            start = node.body[1].lineno
        return dict(path=path, symbol=symbol, start_line=start, end_line=end,
                    content=''.join(info['lines'][start-1:end]), content_hash=info['hash'],
                    symbol_range=[begin, end], complete_symbol=start == begin,
                    signature=symbol + '(' + ast.unparse(node.args) + ')', reason=reason, score=0)

    for row in primary:
        path, owner = row['path'], row['symbol'].rsplit('.', 1)[0]
        family = bases(path, owner)
        leaves = {r['symbol'].rsplit('.', 1)[-1] for r in primary if r['path'] == path}
        for p, parent in family:
            for symbol, (_, _, node) in index.parsed[p]['symbols'].items():
                if symbol.rsplit('.', 1)[0] != parent or symbol.rsplit('.', 1)[-1] in leaves:
                    continue
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                calls = [n.func.attr for n in ast.walk(node) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                         and n.func.value.id == 'self']
                if not leaves.intersection(calls):
                    continue
                additions.append(fragment(p, symbol, 'same_family_consumer'))
                for name in calls:
                    if name in leaves:
                        continue
                    for dep_path, dep_owner in family:
                        target = dep_owner + '.' + name
                        if target in index.parsed[dep_path]['symbols']:
                            additions.append(fragment(dep_path, target, 'effective_self_dispatch'))
                            break
    evidence, discarded, used = [], [], 0
    for row in [*primary, *additions, *baseline['evidence']]:
        if any(r['path'] == row['path'] and r['start_line'] <= row['end_line']
               and row['start_line'] <= r['end_line'] for r in evidence):
            continue
        if len(evidence) >= 5 or used + len(row['content']) > 6000:
            discarded.append({'path': row['path'], 'symbol': row['symbol'], 'reason': 'budget'})
            continue
        evidence.append(row)
        used += len(row['content'])
    validate_evidence(workspace, allowed, evidence)
    return {'evidence': evidence, 'metadata': {'policy': 'caller-fallback-context-v1', 'chars': used,
            'max_chars': 6000, 'max_fragments': 5, 'discarded': discarded,
            'public_api_owners': baseline['metadata']['public_api_owners'],
            'source': 'Public API, same inheritance family callers and effective self dispatch only'}}
