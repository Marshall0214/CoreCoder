"""Description-driven symbol coverage and one-hop AST dependencies within 6000 chars."""
import ast
import re

from docs.experiments.function_index_audit_v1 import FunctionIndex
from docs.experiments.function_index_repair_v1 import validate_evidence
from evals.symbol_context import dependency_refs


def retrieve(workspace, allowed, description):
    index = FunctionIndex(workspace, allowed)
    index.refresh()
    words = set(re.findall(r'[A-Za-z_]\w*', description))
    chunks = {(c.path, c.start_line, c.end_line): c for c in index.chunks}
    priorities, reasons = {}, {}
    owners = {(path, name) for path, info in index.parsed.items()
              for name, (_, _, node) in info['symbols'].items()
              if isinstance(node, ast.ClassDef) and name.rsplit('.', 1)[-1] in words}
    for word in sorted(words):
        matches = [k for k, name in index.names.items() if name.rsplit('.', 1)[-1] == word]
        scoped = [k for k in matches if (k[0], index.names[k].rsplit('.', 1)[0]) in owners]
        if scoped:
            matches = scoped
        else:
            matches = [k for k in matches if '.' not in index.names[k]
                       or index.names[k] in description]
        if len(matches) == 1:
            priorities[matches[0]], reasons[matches[0]] = 100, 'exact_description_symbol'
    protocols = set()
    lowered = description.lower()
    if re.search(r'\b(nonmember\w*|member\w*|contain\w*|recognize)\b', lowered):
        protocols.add('__contains__')
    if re.search(r'\b(length|len)\b', lowered):
        protocols.update(('__len__', '_len'))
    if re.search(r'\b(yields?|iteration|iterates?)\b', lowered):
        protocols.add('__iter__')
    for key, name in index.names.items():
        if '.' in name and (key[0], name.rsplit('.', 1)[0]) in owners:
            priorities.setdefault(key, 40)
            reasons.setdefault(key, 'mentioned_class_method')
            if name.rsplit('.', 1)[-1] in protocols:
                priorities[key], reasons[key] = 90, 'description_protocol_method'
    # Resolve only original AST references; no model selection or grader contents.
    seeds = [k for k, priority in priorities.items() if priority >= 90]
    for key in sorted(seeds):
        path, start, end = key
        for other, target in sorted(dependency_refs(index.parsed[path], start, end, index.names[key])):
            other = other or path
            for candidate, name in index.names.items():
                if candidate[0] == other and name == target and priorities.get(candidate, 0) < 60:
                    priorities[candidate], reasons[candidate] = 60, 'direct_ast_dependency'
    scores = {(c.path, c.start_line, c.end_line): score for score, c in index.rank(description)}
    ranked = sorted(chunks, key=lambda k: (-priorities.get(k, 0), -scores.get(k, 0), k))
    evidence, omitted, used = [], [], 0
    for key in ranked:
        if len(evidence) == 5:
            break
        path, start, end = key
        info, name = index.parsed[path], index.names[key]
        node = info['symbols'][name][2]
        full_start = start
        # Long docstrings must not cause the target implementation to disappear.
        # Keep a contiguous exact body; never fabricate editable source by joining gaps.
        doc = node.body[0] if node.body else None
        compact = isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant) and isinstance(doc.value.value, str)
        if compact and len(''.join(info['lines'][start - 1:end])) > 1200 and len(node.body) > 1:
            start = node.body[1].lineno
        content = ''.join(info['lines'][start - 1:end])
        if used + len(content) > 6000:
            omitted.append({'path': path, 'symbol': name, 'reason': 'budget', 'chars': len(content)})
            continue
        if any(r['path'] == path and r['start_line'] <= end and start <= r['end_line'] for r in evidence):
            continue
        evidence.append({'path': path, 'symbol': name, 'start_line': start, 'end_line': end,
                         'content': content, 'content_hash': info['hash'],
                         'symbol_range': [full_start, end], 'complete_symbol': start == full_start,
                         'signature': name + '(' + ast.unparse(node.args) + ')',
                         'reason': reasons.get(key, 'keyword_fallback'), 'score': scores.get(key, 0)})
        used += len(content)
    validate_evidence(workspace, allowed, evidence)
    return {'evidence': evidence, 'metadata': {'policy': 'targeted-context-v1', 'chars': used,
            'max_chars': 6000, 'max_fragments': 5, 'discarded': omitted,
            'required_symbols': [{'path': k[0], 'symbol': index.names[k]} for k in ranked
                                 if priorities.get(k, 0) >= 90],
            'missing_required': [{'path': k[0], 'symbol': index.names[k]} for k in ranked
                                 if priorities.get(k, 0) >= 90 and not any(
                                     r['path'] == k[0] and r['symbol'] == index.names[k] for r in evidence)]}}
