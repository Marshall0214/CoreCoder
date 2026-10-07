"""Bounded source facts for publicly named classes; no inferred repair rules."""

import ast
import hashlib
import json
import re

from docs.experiments import unified_feedback_worker_v1 as unified

LIMIT = 6000
FACT_LIMIT = 2000


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def facts(workspace, allowed, description):
    index = unified.context.public.comparison.directed.retrieval.FunctionIndex(workspace, allowed)
    index.refresh()
    _, resolved = unified.context.public.comparison.directed.resolve_symbols(index, description)
    words = set(re.findall(r'[A-Za-z_]\w*', description))
    groups = []
    for owner in resolved['class_mentions']:
        path, name = owner['path'], owner['symbol']
        info = index.parsed[path]
        start, end, cls = info['symbols'][name]
        methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        params = {a.arg for method in methods for a in (*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs)}
        params = (params & words) - {'self', 'cls'}
        if not params:
            continue
        data = (workspace / path).read_bytes()
        members = set()
        for node in ast.walk(cls):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
            for target in targets:
                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                    if any(param in target.attr for param in params):
                        members.add(target.attr)
                elif isinstance(target, ast.Name) and any(param in target.id for param in params):
                    members.add(target.id)
        header = f'{path} sha256={hashlib.sha256(data).hexdigest()}\n{name} L{start}-{end} bases={[ast.unparse(b) for b in cls.bases]} locally assigned parameter-related members={sorted(members)}; inherited/dynamic members unknown.'
        rows = [header]
        for method in methods:
            args = [*method.args.posonlyargs, *method.args.args]
            defaults = dict(zip([a.arg for a in args[len(args)-len(method.args.defaults):]], method.args.defaults))
            defaults.update({a.arg: v for a, v in zip(method.args.kwonlyargs, method.args.kw_defaults) if v is not None})
            used = {a.arg for a in (*args, *method.args.kwonlyargs)} & params
            if not used:
                continue
            statements = []
            for node in ast.walk(method):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
                    attrs = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
                    if used & (names | attrs):
                        statements.append(f'L{node.lineno} {ast.unparse(node)}')
                elif isinstance(node, ast.If) and used & {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}:
                    statements.append(f'L{node.lineno} if {ast.unparse(node.test)}')
                elif isinstance(node, ast.Call):
                    expressions = [*node.args, *(k.value for k in node.keywords)]
                    if used & {n.id for value in expressions for n in ast.walk(value) if isinstance(n, ast.Name)}:
                        statements.append(f'L{node.lineno} call {ast.unparse(node)}')
            if statements or method.name == '__init__':
                defaults_text = ','.join(f'{p}={ast.unparse(defaults[p]) if p in defaults else "<required>"}' for p in sorted(used))
                rows.append(f'{name}.{method.name} L{method.lineno}-{method.end_lineno} {defaults_text}: ' + '; '.join(dict.fromkeys(statements)))
        groups.append(rows)
    # Round robin preserves both class headers/defaults before longer forwarding rows.
    selected, omitted = [], []
    for position in range(max((len(g) for g in groups), default=0)):
        for group in groups:
            if position >= len(group):
                continue
            row = group[position]
            if len(encoded('\n'.join([*selected, row]))) <= FACT_LIMIT:
                selected.append(row)
            else:
                omitted.append(row.split(':', 1)[0])
    return '\n'.join(selected), {'omitted_fact_rows': omitted, 'inference': 'static local facts only; no expected fix or runtime proof'}


def pack(workspace, job):
    sheet, metadata = facts(workspace, job['allowed_files'], job['description'])
    candidates = unified.context.forwarding_context(workspace, job['allowed_files'], job['evidence'], job['description'])
    remaining = LIMIT - len(encoded(sheet))
    evidence, omitted = [], []
    for row in candidates['evidence']:
        if len(row['content']) <= remaining:
            evidence.append(row)
            remaining -= len(row['content'])
        else:
            omitted.append(row['symbol'])
    unified.repair.validate_evidence(workspace, job['allowed_files'], evidence)
    metadata.update(contract_chars=len(encoded(sheet)), evidence_chars=sum(len(r['content']) for r in evidence),
                    combined_chars=LIMIT-remaining, max_chars=LIMIT, omitted_symbols=omitted,
                    strategy='source-facts-plus-constructor-forwarding', seed_count=len(evidence))
    return {'evidence': evidence, 'source_contract_facts': sheet, 'metadata': metadata}

