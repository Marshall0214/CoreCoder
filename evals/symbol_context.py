"""Offline Python symbol evidence with bounded static dependency expansion."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

from corecoder.retrieval.keyword import KeywordIndex, terms

from .fixed_evidence import apply_patch_json
from .real_admission import DATA
from .real_tasks import admitted_case
from .runner import digest, implementation_metadata, snapshot
from .runtime import Events
from .schema import relative_path


def module_name(path):
    parts = path.removesuffix('.py').split('/')
    if parts[0] == 'src':
        parts = parts[1:]
    if parts[-1] == '__init__':
        parts = parts[:-1]
    return '.'.join(parts)


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted(node.value)
        return base + '.' + node.attr if base else ''
    return ''


def parse_source(path, data, modules):
    text = data.decode('utf-8')
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {'lines': text.splitlines(keepends=True), 'tree': None, 'symbols': {}, 'bindings': {}}
    symbols = {}

    def visit(nodes, prefix=''):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + node.name
                start = min([node.lineno] + [item.lineno for item in node.decorator_list])
                symbols[name] = (start, node.end_lineno, node)
                visit(node.body, name + '.')
            elif isinstance(node, (ast.If, ast.Try, ast.With)):
                visit(node.body, prefix)
                visit(getattr(node, 'orelse', []), prefix)
    visit(tree.body)
    package = module_name(path).split('.')
    if not path.endswith('/__init__.py'):
        package = package[:-1]
    bindings = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name in modules:
                    bindings[item.asname or item.name] = (modules[item.name], '')
        elif isinstance(node, ast.ImportFrom):
            if node.level > len(package):
                continue
            prefix = package[:len(package) - node.level + 1] if node.level else []
            base = '.'.join(prefix + (node.module.split('.') if node.module else []))
            for item in node.names:
                if item.name == '*':
                    continue
                imported = base + '.' + item.name if base else item.name
                if imported in modules:
                    bindings[item.asname or item.name] = (modules[imported], '')
                elif base in modules:
                    bindings[item.asname or item.name] = (modules[base], item.name)
    return {'lines': text.splitlines(keepends=True), 'tree': tree, 'symbols': symbols, 'bindings': bindings}


def dependency_refs(info, start, end, symbol):
    refs = set()
    if info['tree'] is None:
        return refs
    for node in ast.walk(info['tree']):
        if not start <= getattr(node, 'lineno', 0) <= end:
            continue
        name = dotted(node)
        if not name:
            continue
        for alias, (path, imported) in info['bindings'].items():
            if name == alias or name.startswith(alias + '.'):
                suffix = name[len(alias):].lstrip('.')
                target = '.'.join(part for part in (imported, suffix) if part)
                if target:
                    refs.add((path, target))
        if name in info['symbols']:
            refs.add(('', name))
        if name.startswith(('self.', 'cls.')) and '.' in symbol:
            target = symbol.rsplit('.', 1)[0] + '.' + name.split('.', 1)[1]
            if target in info['symbols']:
                refs.add(('', target))
    return refs


def symbol_evidence(workspace, description, allowed_files, events, max_chars=6000, top_k=5, depth=1,
                    index_mode='legacy-lines', query_policy='plain', packing_policy='seed-first'):
    from .symbol_index import PythonCodeIndex, expand_query

    if index_mode not in {'legacy-lines', 'lines', 'symbols'}:
        raise ValueError('Unknown symbol context index mode')
    if packing_policy not in {'seed-first', 'dependency-reserve'}:
        raise ValueError('Unknown symbol context packing policy')
    if (not isinstance(max_chars, int) or isinstance(max_chars, bool) or not 256 <= max_chars <= 20000
            or not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 20
            or not isinstance(depth, int) or isinstance(depth, bool) or not 0 <= depth <= 3):
        raise ValueError('Invalid symbol evidence limits')
    workspace = workspace.resolve()
    allowed = {relative_path(name) for name in allowed_files}
    modules = {module_name(name): name for name in sorted(allowed)}
    index = (KeywordIndex(workspace, allowed) if index_mode == 'legacy-lines'
             else PythonCodeIndex(workspace, allowed, index_mode))
    metadata = index.refresh()
    versions = {chunk.path: chunk.content_hash for chunk in index.chunks}
    query = expand_query(description, query_policy)
    ranked = index.rank(query)
    cache, queue, seeds = {}, [], []

    def source(name):
        path = workspace / name
        if not path.resolve().is_relative_to(workspace) or any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Evidence path is linked or escaped workspace')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != versions.get(name):
            raise ValueError('Indexed source version changed')
        if name not in cache:
            cache[name] = parse_source(name, data, modules)
        return cache[name]

    query_terms = set(terms(query))
    for score, chunk in ranked:
        if chunk.path not in allowed or not chunk.path.endswith('.py'):
            continue
        info = source(chunk.path)
        anchor = max(range(chunk.start_line, chunk.end_line + 1),
                     key=lambda line: len(query_terms & set(terms(info['lines'][line - 1]))))
        candidates = [(end - start, name, start, end) for name, (start, end, _) in info['symbols'].items()
                      if start <= anchor <= end]
        if candidates:
            _, name, start, end = min(candidates)
        else:
            name, start, end = '<line-window>', chunk.start_line, chunk.end_line
        key = (chunk.path, start, end)
        if any(seed['key'] == key for seed in seeds):
            continue
        seeds.append({'key': key, 'score': round(score, 6)})
        fallback = ((chunk.start_line, chunk.end_line) if index_mode != 'symbols'
                    else (max(start, anchor - 19), min(end, anchor + 20)))
        queue.append((chunk.path, name, start, end, 0, 'keyword', fallback))
        if len(seeds) >= top_k:
            break
    seed_limit = max_chars // 2 if packing_policy == 'dependency-reserve' and depth else max_chars
    selected, discarded, edges, visited, used = [], [], [], set(), 0
    seed_chars = 0
    while queue:
        path, symbol, start, end, level, reason, fallback = queue.pop(0)
        key = (path, start, end)
        if key in visited:
            continue
        visited.add(key)
        info = source(path)
        original_range = [start, end]
        complete = symbol != '<line-window>'
        content = ''.join(info['lines'][start - 1:end])
        available = min(max_chars - used, seed_limit - seed_chars) if level == 0 else max_chars - used
        if len(content) > available and fallback is not None:
            start, end = max(start, fallback[0]), min(end, fallback[1])
            content = ''.join(info['lines'][start - 1:end])
            complete = False
        if any(row['path'] == path and row['start_line'] <= end and start <= row['end_line'] for row in selected):
            discarded.append({'path': path, 'symbol': symbol, 'reason': 'overlap'})
            continue
        if not content.strip() or len(selected) >= 20 or len(content) > available:
            discarded.append({'path': path, 'symbol': symbol, 'reason': 'budget', 'chars': len(content),
                              'available_chars': available, 'depth': level})
            continue
        selected.append({'path': path, 'symbol': symbol, 'start_line': start, 'end_line': end,
                         'symbol_range': original_range, 'complete_symbol': complete,
                         'content_hash': versions[path], 'content': content, 'depth': level, 'reason': reason,
                         'parse_status': 'valid' if info['tree'] else 'syntax-error-window'})
        used += len(content)
        if level == 0:
            seed_chars += len(content)
        if level >= depth:
            continue
        for other, target in sorted(dependency_refs(info, start, end, symbol)):
            other = other or path
            if other not in versions:
                continue
            target_info = source(other)
            names = [name for name in target_info['symbols'] if target == name or target.startswith(name + '.')]
            if not names:
                continue
            resolved = max(names, key=len)
            a, b, _ = target_info['symbols'][resolved]
            edges.append({'from': [path, symbol], 'to': [other, resolved], 'reason': 'static-reference'})
            queue.append((other, resolved, a, b, level + 1, 'static-reference', None))
    events.emit('symbol_evidence_built', query=query, public_description=description,
                index_mode=index_mode, query_policy=query_policy, index=metadata, max_chars=max_chars,
                packing_policy=packing_policy, seed_limit=seed_limit, seed_chars=seed_chars,
                dependency_chars=used - seed_chars,
                top_k=top_k, dependency_depth=depth, evidence_chars=used, seeds=seeds,
                selected=[{k: v for k, v in row.items() if k != 'content'} for row in selected],
                discarded=discarded, dependency_edges=edges)
    return selected


def apply_symbol_patch(content, workspace, allowed_files, evidence):
    """A partial-context patch must match text actually supplied, as well as the full-file version."""
    parsed = json.loads(content)
    if not isinstance(parsed, dict) or set(parsed) != {'edits'} or not isinstance(parsed['edits'], list):
        raise ValueError('Expected exactly an edits array')
    hashes = {}
    for row in evidence:
        if row['path'] in hashes and hashes[row['path']] != row['content_hash']:
            raise ValueError('Inconsistent evidence versions')
        hashes[row['path']] = row['content_hash']
    for edit in parsed['edits']:
        if (not isinstance(edit, dict) or set(edit) != {'file', 'old', 'new'}
                or not all(isinstance(value, str) for value in edit.values()) or not edit['old']):
            raise ValueError('Invalid edit fields')
        if not any(row['path'] == edit['file'] and edit['old'] in row['content'] for row in evidence):
            raise ValueError('Edit text was not supplied in local context')
    return apply_patch_json(content, workspace, allowed_files, evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, default=DATA / 'crossfile-candidates.json')
    parser.add_argument('--task', default='click-flag-envvar')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--index-mode', choices=('legacy-lines', 'lines', 'symbols'), default='legacy-lines')
    parser.add_argument('--query-policy', choices=('plain', 'aliases', 'identifiers'), default='plain')
    parser.add_argument('--packing-policy', choices=('seed-first', 'dependency-reserve'), default='seed-first')
    args = parser.parse_args()
    case, _, checks, source, _ = admitted_case(args.admission.resolve(), args.catalog, args.task)
    output = args.output.resolve()
    if output.is_relative_to(source.resolve()) or output.is_relative_to(checks.resolve()):
        raise ValueError('Output must stay outside admitted sources and checks')
    output.mkdir(parents=True, exist_ok=False)
    original = digest(snapshot(source / 'before'))
    allowed = sorted(path.relative_to(source / 'before').as_posix()
                     for path in (source / 'before/src/click').rglob('*.py'))
    evidence = symbol_evidence(source / 'before', case['public_problem'], allowed,
                               Events(output / 'trace.jsonl', 'symbol-context-offline'),
                               index_mode=args.index_mode, query_policy=args.query_policy,
                               packing_policy=args.packing_policy)
    if digest(snapshot(source / 'before')) != original:
        raise ValueError('Evidence construction mutated upstream source')
    report = {'protocol': 'symbol-context-offline-v1', 'source_hash': original,
              'implementation': implementation_metadata(),
              'config': {'max_chars': 6000, 'top_k': 5, 'dependency_depth': 1,
                         'index_mode': args.index_mode, 'query_policy': args.query_policy,
                         'packing_policy': args.packing_policy},
              'model_calls': 0, 'evidence_chars': sum(len(row['content']) for row in evidence),
              'evidence': evidence, 'scope': 'development selection diagnostic; not model repair'}
    (output / 'evidence.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output / 'evidence.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
