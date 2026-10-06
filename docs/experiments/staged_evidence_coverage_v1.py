"""Offline public-name and source-span coverage on immutable localization checkpoints."""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.real_admission import DATA
from evals.real_suite import file_hash, load_manifest
from evals.schema import RunConfig, relative_path
from evals.staged_repair import select_evidence, validate_localization


def covered_lines(rows, path):
    return {line for row in rows if row['path'] == path
            for line in range(row['start_line'], row['end_line'] + 1)}


def public_anchors(description, sources, bare_names=()):
    """Exact public identifiers only; no tests, fix locations or semantic relevance labels."""
    words = set(re.findall(r'\b[A-Za-z_]\w*\b', description))
    explicit = {word for word in words if '_' in word}
    dotted = set(re.findall(r'\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b', description))
    if not set(bare_names) <= words:
        raise ValueError('Bare names must occur verbatim in the public description')
    definition_names = explicit | set(bare_names)
    anchors = []
    for path, text in sorted(sources.items()):
        tree = ast.parse(text)
        # Dotted public names restrict definitions to their owner (Context.invoke).
        def visit(node, owners=(), source_path=path):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = '.'.join((*owners, node.name))
                named_by_dot = any(name.rsplit('.', 1)[-1] == node.name for name in dotted)
                if (qualified in dotted or (node.name in definition_names and not named_by_dot)):
                    # A class name anchors its declaration, not its entire implementation.
                    end = node.lineno if isinstance(node, ast.ClassDef) else node.end_lineno
                    anchors.append({'name': qualified, 'path': source_path, 'kind': 'definition',
                                    'start_line': node.lineno, 'end_line': end})
                owners = (*owners, node.name)
            name = (node.id if isinstance(node, ast.Name) else
                    node.attr if isinstance(node, ast.Attribute) else
                    node.arg if isinstance(node, (ast.arg, ast.keyword)) else None)
            if name in explicit:
                anchors.append({'name': name, 'path': source_path, 'kind': 'identifier',
                                'start_line': node.lineno, 'end_line': node.lineno})
            for child in ast.iter_child_nodes(node):
                visit(child, owners)

        visit(tree)
    return [dict(items) for items in sorted({tuple(row.items()) for row in anchors})]


def diagnose(description, sources, pool, limit, policy, bare_names=()):
    candidates = pool['reads'] + pool['seeds']
    selected = select_evidence(pool['reads'], pool['seeds'], limit, policy)
    packing, used, seen = [], 0, set()
    ordered = candidates if policy == 'read-first' else pool['seeds'] + pool['reads']
    for row in ordered:
        key = (row['path'], row['start_line'], row['end_line'], row['content_hash'])
        size = len(row['content'])
        reason = ('duplicate' if key in seen else 'larger_than_limit' if size > limit else
                  'remaining_capacity' if used + size > limit else 'selected')
        if reason == 'selected':
            used += size
            seen.add(key)
        packing.append({**{k: row[k] for k in ('path', 'start_line', 'end_line', 'reason')},
                        'chars': size, 'decision': reason})
    coverage = []
    for anchor in public_anchors(description, sources, bare_names):
        span = set(range(anchor['start_line'], anchor['end_line'] + 1))
        in_pool = span & covered_lines(candidates, anchor['path'])
        visible = span & covered_lines(selected, anchor['path'])
        coverage.append({**anchor, 'span_lines': len(span), 'pool_lines': len(in_pool),
                         'visible_lines': len(visible), 'selection_lost_lines': len(in_pool - visible),
                         'pool_missing': not in_pool, 'pool_partial': 0 < len(in_pool) < len(span),
                         'fully_visible': visible == span})
    return {'policy': policy, 'limit_chars': limit, 'selected_chars': used,
            'selected_fragments': len(selected), 'packing': packing, 'anchors': coverage,
            'summary': {'anchor_count': len(coverage),
                        **{key: sum(bool(row[key]) for row in coverage)
                           for key in ('pool_missing', 'pool_partial', 'fully_visible')},
                        'selection_loss_anchors': sum(row['selection_lost_lines'] > 0 for row in coverage)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', required=True, metavar='SOURCE=PATH',
                        help='Admission directory containing TASK/before; only before source is read')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    roots = {}
    for value in args.source:
        name, separator, path = value.partition('=')
        if not separator or not path or name in roots:
            parser.error('Supply unique SOURCE=PATH entries')
        roots[name] = Path(path).resolve()
    protocol_path = DATA / 'staged-shared-repeat-v1.json'
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    manifest = DATA / relative_path(protocol['manifest'])
    if file_hash(manifest) != protocol['manifest_sha256']:
        raise ValueError('Frozen manifest changed')
    data, entries = load_manifest(manifest)
    if set(roots) != {name for name, _, _ in entries}:
        raise ValueError('Supply exactly the frozen suite source groups')
    output = args.output.resolve()
    checkpoint_paths = [ROOT / relative_path(row['path']) for row in protocol['checkpoints'].values()]
    if output.exists() or any(output.is_relative_to(path) for path in
                              [*roots.values(), *(path.parent.resolve() for path in checkpoint_paths)]):
        raise ValueError('Use a fresh output outside source and checkpoint directories')
    tasks = []
    for name, catalog, task in entries:
        record = protocol['checkpoints'][task]
        path = ROOT / relative_path(record['path'])
        if not path.resolve().is_relative_to(ROOT) or file_hash(path) != record['sha256']:
            raise ValueError('Frozen checkpoint file changed')
        checkpoint = json.loads(path.read_text(encoding='utf-8'))
        cases = json.loads(catalog.read_text(encoding='utf-8'))['cases']
        description = next(row['public_problem'] for row in cases if row['case_id'] == task)
        workspace = roots[name] / task / 'before'
        validate_localization(checkpoint, workspace, description, checkpoint['allowed_files'], RunConfig(**data['config']))
        sources = {file: (workspace / relative_path(file)).read_text(encoding='utf-8')
                   for file in checkpoint['allowed_files']}
        # These literal function names occur in the public problem; ordinary prose
        # (e.g. "name", "option", "callback") must not become code anchors.
        bare_names = ('prompt', 'confirm') if task == 'click-prompt-suffix' else ()
        tasks.append({'task_id': task, 'description': description, 'checkpoint_sha256': file_hash(path),
                      'source_hashes': checkpoint['source_hashes'],
                      'bare_public_names': list(bare_names),
                      'policies': [diagnose(description, sources, checkpoint['pool'], data['config']['search_max_chars'], policy, bare_names)
                                   for policy in ('read-first', 'seed-first')]})
    report = {'purpose': 'offline-public-name-coverage-v1', 'benchmark_eligible': False,
              'model_calls': 0, 'diagnostic_sha256': file_hash(Path(__file__)),
              'protocol_sha256': file_hash(protocol_path), 'tasks': tasks,
              'limitations': 'Exact public names and AST spans are diagnostic anchors, not necessary repair locations. '
                             'Partial spans do not establish truncation cause. No hidden tests or reference fixes read.'}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'coverage.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for task in tasks:
        for policy in task['policies']:
            print(task['task_id'], policy['policy'], policy['selected_chars'], policy['summary'])
    print(output / 'coverage.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
