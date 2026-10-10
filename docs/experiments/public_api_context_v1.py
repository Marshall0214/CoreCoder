"""Description-driven symbol coverage and one-hop AST dependencies within 6000 chars."""
import ast
import re

from docs.experiments.function_index_audit_v1 import FunctionIndex
from docs.experiments.function_index_repair_v1 import validate_evidence
from evals.symbol_context import dependency_refs


def retrieve(workspace, allowed, description, public_code=""):
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
    # Bare prose such as "command-line" must not promote command()/argument().
    from docs.experiments.symbol_directed_retrieval_v1 import explicit_mentions
    explicit = set(explicit_mentions(description))
    for key in list(priorities):
        if reasons[key] == 'direct_ast_dependency' or (reasons[key] == 'exact_description_symbol' and index.names[key].rsplit('.', 1)[-1] not in explicit):
            del priorities[key]
            del reasons[key]
    # Public API factories identify relevant classes without executing repository code.
    public_tree = ast.parse(public_code) if public_code else ast.parse('')
    factory_names = {n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id
                     for n in ast.walk(public_tree) if isinstance(n, ast.Call)
                     and isinstance(n.func, (ast.Attribute, ast.Name))}
    classes = {(path, name): node for path, info in index.parsed.items()
               for name, (_, _, node) in info['symbols'].items() if isinstance(node, ast.ClassDef)}
    api_owners = set()
    for key, name in index.names.items():
        if '.' in name or name not in factory_names:
            continue
        info = index.parsed[key[0]]
        node = info['symbols'][name][2]
        for ref in ast.walk(node):
            if not isinstance(ref, ast.Name):
                continue
            binding = info['bindings'].get(ref.id)
            target = binding if binding else (key[0], ref.id)
            if target in classes:
                api_owners.add(target)
    from corecoder.retrieval.keyword import terms
    query_words = set(terms(description))
    query_words.update(k.arg for n in ast.walk(public_tree) if isinstance(n, ast.Call)
                       for k in n.keywords if k.arg)
    # Split keywords as source method names are also split (e.g. default_map).
    query_words = set(terms(' '.join(query_words))) - {'get', 'value', 'from', 'to', 'is', 'the', 'and', 'or'}
    public_keywords = {k.arg for n in ast.walk(public_tree) if isinstance(n, ast.Call) for k in n.keywords if k.arg}
    for key, name in index.names.items():
        if '.' not in name or (key[0], name.rsplit('.', 1)[0]) not in api_owners:
            continue
        matched = set(terms(name.rsplit('.', 1)[-1])) & query_words
        if matched:
            ctor = index.parsed[key[0]]['symbols'].get(name.rsplit('.', 1)[0] + '.__init__')
            params = {a.arg for a in (*ctor[2].args.args, *ctor[2].args.kwonlyargs)} if ctor else set()
            specificity = 10 if public_keywords & params else 0
            priorities[key] = max(priorities.get(key, 0), 80 + specificity + 5 * len(matched))
            reasons[key] = 'public_factory_class_method'
    # Resolve super().method against direct source bases; never guess across modules.
    seeds = [k for k, v in priorities.items() if v >= 80]
    for key in sorted(seeds):
        path, start, end = key
        name = index.names[key]
        refs = set(dependency_refs(index.parsed[path], start, end, name))
        if '.' in name:
            owner = name.rsplit('.', 1)[0]
            cls = classes.get((path, owner))
            if cls:
                for node in ast.walk(index.parsed[path]['symbols'][name][2]):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and isinstance(node.func.value, ast.Call)
                            and isinstance(node.func.value.func, ast.Name)
                            and node.func.value.func.id == 'super'):
                        for base in cls.bases:
                            if isinstance(base, ast.Name):
                                base_path, base_name = index.parsed[path]['bindings'].get(base.id, (path, base.id))
                                refs.add((base_path, base_name + '.' + node.func.attr))
        for other, target in sorted(refs):
            for candidate, candidate_name in index.names.items():
                if candidate[0] == (other or path) and candidate_name == target:
                    if priorities.get(candidate, 0) < 88:
                        priorities[candidate], reasons[candidate] = 88, 'public_api_static_dependency'
    # Typed receiver calls such as ctx.lookup_default resolve to Context methods.
    for key in sorted(k for k, v in priorities.items() if v >= 88):
        path = key[0]
        info = index.parsed[path]
        node = info['symbols'][index.names[key]][2]
        typed = {}
        for arg in (*node.args.args, *node.args.kwonlyargs):
            if isinstance(arg.annotation, ast.Name):
                typed[arg.arg] = info['bindings'].get(arg.annotation.id, (path, arg.annotation.id))
        for call in ast.walk(node):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name) and call.func.value.id in typed):
                owner_path, owner_name = typed[call.func.value.id]
                for candidate, name in index.names.items():
                    if candidate[0] == owner_path and name == owner_name + '.' + call.func.attr:
                        if priorities.get(candidate, 0) < 88:
                            priorities[candidate], reasons[candidate] = 88, 'typed_receiver_dependency'
    # Include a direct caller in the same inheritance family, excluding shadowed
    # base alternatives to already-selected overriding methods.
    family = set(api_owners)
    for path, owner in sorted(api_owners):
        for base in classes[(path, owner)].bases:
            if isinstance(base, ast.Name):
                family.add(index.parsed[path]['bindings'].get(base.id, (path, base.id)))
    leaves = {index.names[k].rsplit('.', 1)[-1] for k, v in priorities.items()
              if v >= 90 and reasons.get(k) == 'public_factory_class_method'}
    for key, name in index.names.items():
        if '.' not in name or (key[0], name.rsplit('.', 1)[0]) not in family:
            continue
        if name.rsplit('.', 1)[-1] in leaves:
            continue
        node = index.parsed[key[0]]['symbols'][name][2]
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and isinstance(n.func.value, ast.Name) and n.func.value.id in {'self', 'cls'}
               and n.func.attr in leaves for n in ast.walk(node)):
            if priorities.get(key, 0) < 87:
                priorities[key], reasons[key] = 87, 'same_family_direct_caller'
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
        if compact and len(''.join(info['lines'][start - 1:end])) > 600 and len(node.body) > 1:
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
    return {'evidence': evidence, 'metadata': {'policy': 'public-api-context-v1', 'chars': used,
            'max_chars': 6000, 'max_fragments': 5, 'discarded': omitted,
            'public_api_owners': [{'path': p, 'symbol': n} for p, n in sorted(api_owners)],
            'required_symbols': [{'path': k[0], 'symbol': index.names[k]} for k in ranked
                                 if priorities.get(k, 0) >= 90],
            'missing_required': [{'path': k[0], 'symbol': index.names[k]} for k in ranked
                                 if priorities.get(k, 0) >= 90 and not any(
                                     r['path'] == k[0] and r['symbol'] == index.names[k] for r in evidence)]}}
