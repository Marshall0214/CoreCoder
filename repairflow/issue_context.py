"""Pack real module bindings and local helpers within the existing evidence budget."""
import ast
import hashlib
from pathlib import Path

from docs.experiments.coverage_context_v2 import retrieve as baseline_retrieve
from docs.experiments.coverage_context_v2 import validate_evidence
from evals.schema import relative_path

MAX_CHARS = 6000
MAX_FRAGMENTS = 5
MAX_IMPORT_CHARS = 1200


def call_names(tree):
    return {node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))}


def retrieve(workspace, allowed, description, public_code=''):
    workspace = Path(workspace).resolve()
    for name in allowed:
        relative_path(name)
        path = workspace / name
        if path.is_symlink() or not path.resolve().is_relative_to(workspace) or not path.is_file():
            raise ValueError('Context path is outside allowed source')
    baseline = baseline_retrieve(workspace, allowed, description, public_code)
    validate_evidence(workspace, allowed, baseline['evidence'])
    required = {tuple(pair) for pair in baseline['metadata']['required']}
    primary = [row for row in baseline['evidence'] if (row['path'], row['symbol']) in required]
    if not primary:
        primary = baseline['evidence'][:1]
    if not primary:
        raise ValueError('No target evidence available')
    try:
        public_names = call_names(ast.parse(public_code))
    except SyntaxError:
        public_names = set()
    imports, helpers, direct = [], [], []
    for name in dict.fromkeys(row['path'] for row in primary):
        data = (workspace / name).read_bytes()
        lines = data.decode('utf-8').splitlines(keepends=True)
        tree = ast.parse(data)
        version = hashlib.sha256(data).hexdigest()

        def row(start, end, symbol, reason, name=name, lines=lines, version=version):
            return {'path': name, 'symbol': symbol, 'start_line': start, 'end_line': end,
                    'content': ''.join(lines[start - 1:end]), 'content_hash': version,
                    'reason': reason, 'complete_symbol': True}

        # Join adjacent module imports, never stringify AST or fabricate source citations.
        block = None
        for node in tree.body:
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                block = None
                continue
            if block is not None and len(''.join(lines[block['start_line'] - 1:node.end_lineno])) <= MAX_IMPORT_CHARS:
                block.update(end_line=node.end_lineno, content=''.join(lines[block['start_line'] - 1:node.end_lineno]))
            else:
                block = row(node.lineno, node.end_lineno, '<module-imports>', 'module_import_bindings')
                imports.append(block)
        targets = {r['symbol'] for r in primary if r['path'] == name}
        referenced = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in targets:
                referenced.update(call_names(node))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name in targets:
                continue
            if node.name not in public_names | referenced:
                continue
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            helper = row(start, node.end_lineno, node.name,
                         'public_test_referenced_helper' if node.name in public_names else 'target_direct_helper')
            (helpers if node.name in public_names else direct).append(helper)
    selected, discarded = [], list(baseline['metadata'].get('discarded', []))
    used, import_chars = 0, 0
    for candidate in [*primary, *imports, *helpers, *direct, *baseline['evidence']]:
        is_import = candidate['reason'] == 'module_import_bindings'
        reason = None
        if any(r['path'] == candidate['path'] and r['start_line'] <= candidate['end_line']
               and candidate['start_line'] <= r['end_line'] for r in selected):
            reason = 'overlap'
        elif (len(selected) >= MAX_FRAGMENTS or used + len(candidate['content']) > MAX_CHARS
              or is_import and import_chars + len(candidate['content']) > MAX_IMPORT_CHARS):
            reason = 'budget'
        if reason:
            discarded.append({'path': candidate['path'], 'symbol': candidate['symbol'], 'reason': reason})
            continue
        selected.append(candidate)
        used += len(candidate['content'])
        if is_import:
            import_chars += len(candidate['content'])
    if not required <= {(r['path'], r['symbol']) for r in selected}:
        raise ValueError('Required repair target missing after binding packing')
    validate_evidence(workspace, allowed, selected)
    return {'evidence': selected, 'metadata': dict(baseline['metadata'], policy='module-bindings-v1',
            baseline_policy=baseline['metadata']['policy'], chars=used, max_chars=MAX_CHARS,
            max_fragments=MAX_FRAGMENTS, import_chars=import_chars, max_import_chars=MAX_IMPORT_CHARS,
            discarded=discarded)}
