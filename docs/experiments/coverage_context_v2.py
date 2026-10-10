"""Reserve explicit repair subjects and coupled protocols before optional context."""
import ast
import re

from docs.experiments import caller_fallback_context_v2 as previous
from docs.experiments.function_index_audit_v1 import FunctionIndex
from docs.experiments.function_index_repair_v1 import validate_evidence
from docs.experiments.symbol_directed_retrieval_v1 import resolve_symbols


def retrieve(workspace, allowed, description, public_code=''):
    index = FunctionIndex(workspace, allowed)
    index.refresh()
    # Requirement subjects precede must/should/shall; preserve clauses are not edit targets.
    subject = re.split(r'\b(?:must|should|shall)\b', description, maxsplit=1)[0]
    priorities, _ = resolve_symbols(index, subject + ' must')
    required = []
    for key in priorities:
        name = index.names[key]
        leaf = name.rsplit('.', 1)[-1]
        # Qualified names and code-shaped bare identifiers are explicit.
        # Plain prose nouns such as output/option do not force method selection.
        qualified = name in subject and '.' in name
        code_shaped = '_' in leaf or re.search(r'`' + re.escape(leaf) + r'`|' + re.escape(leaf) + r'\s*\(', subject)
        bare_subject = '.' not in name and re.match(r'\s*' + re.escape(leaf) + r'\b', subject)
        if qualified or code_shaped or bare_subject:
            required.append((key[0], name))
    _, full = resolve_symbols(index, description)
    owners = {(x['path'], x['symbol']) for x in full['class_mentions']}
    owners.update((p, n.rsplit('.', 1)[0]) for p, n in required if '.' in n)
    lower = description.lower()
    protocols = set()
    if re.search(r'\b(hash|hashes|hashing)\b', lower) and re.search(r'\b(equal|equality|compare)\b', lower):
        protocols.update(('__eq__', '__hash__'))
    if re.search(r'\b(resource|resources|context-managed)\b', lower) and re.search(r'\b(exception|suppression|exit)\b', lower):
        protocols.add('__exit__')
    if re.search(r'\b(index|membership|nonmember)\b', lower):
        protocols.add('index')
    for path, owner in sorted(owners):
        for leaf in sorted(protocols):
            if owner + '.' + leaf in index.parsed[path]['symbols']:
                required.append((path, owner + '.' + leaf))
    required = list(dict.fromkeys(required))
    rows = []
    for path, name in required:
        info = index.parsed[path]
        begin, end, node = info['symbols'][name]
        start = begin
        doc = node.body[0] if node.body else None
        if (isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant)
                and isinstance(doc.value.value, str) and len(node.body) > 1):
            start = node.body[1].lineno
        rows.append(dict(path=path, symbol=name, start_line=start, end_line=end,
                         content=''.join(info['lines'][start-1:end]), content_hash=info['hash'],
                         symbol_range=[begin, end], complete_symbol=start == begin,
                         signature=name + '(' + ast.unparse(node.args) + ')',
                         reason='required_repair_subject_or_protocol', score=0))
    if len(rows) > 5 or sum(len(r['content']) for r in rows) > 6000:
        raise ValueError('Required repair coverage exceeds fixed context budget')
    baseline = previous.retrieve(workspace, allowed, description, public_code)
    evidence, discarded = [], []
    used = 0
    for row in [*rows, *baseline['evidence']]:
        if any(r['path'] == row['path'] and r['start_line'] <= row['end_line']
               and row['start_line'] <= r['end_line'] for r in evidence):
            continue
        if len(evidence) >= 5 or used + len(row['content']) > 6000:
            discarded.append({'path': row['path'], 'symbol': row['symbol'], 'reason': 'budget'})
            continue
        evidence.append(row)
        used += len(row['content'])
    selected = {(r['path'], r['symbol']) for r in evidence}
    if not set(required) <= selected:
        raise ValueError('Required repair target missing after packing')
    validate_evidence(workspace, allowed, evidence)
    return {'evidence': evidence, 'metadata': {'policy': 'coverage-context-v2', 'chars': used,
            'max_chars': 6000, 'max_fragments': 5, 'required': required, 'missing_required': [],
            'discarded': discarded, 'public_api_owners': baseline['metadata']['public_api_owners']}}
