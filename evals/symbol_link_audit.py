"""Offline audit of missing attribute assignments and constructor-alias links."""

import argparse
import hashlib
import json
from pathlib import Path

from .real_admission import DATA
from .real_tasks import admitted_case
from .runner import digest, implementation_metadata, snapshot
from .runtime import Events
from .schema import relative_path
from .symbol_context import module_name, parse_source, symbol_evidence
from .symbol_links import attribute_assignments, constructor_aliases, linked_refs, resolve_link


def audit(workspace, evidence, allowed_files, depth=1, max_nodes=100, max_edges=300):
    if not 0 <= depth <= 3 or not 1 <= max_nodes <= 200 or not 1 <= max_edges <= 1000:
        raise ValueError('Invalid link audit limits')
    workspace = workspace.resolve()
    names = sorted(set(allowed_files))
    modules = {module_name(name): name for name in names}
    infos, aliases, versions = {}, {}, {}
    for name in names:
        relative_path(name)
        path = workspace / name
        if not path.resolve().is_relative_to(workspace) or any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError('Audit path linked or escaped workspace')
        data = path.read_bytes()
        versions[name] = hashlib.sha256(data).hexdigest()
        if any(row['path'] == name and hashlib.sha256(data).hexdigest() != row['content_hash'] for row in evidence):
            raise ValueError('Evidence source version changed')
        infos[name] = parse_source(name, data, modules)
        aliases[name] = constructor_aliases(infos[name])

    def displayed(path, a, b):
        return any(row['path'] == path and row['start_line'] <= a and b <= row['end_line'] for row in evidence)

    if any(row['path'] not in infos for row in evidence):
        raise ValueError('Evidence is outside allowed audit sources')
    queue = [(row['path'], row['symbol'], 0) for row in evidence if row['symbol'] in infos[row['path']]['symbols']]
    nodes, edges, assignments, visited = [], [], [], set()
    limited = False
    while queue:
        path, symbol, level = queue.pop(0)
        if (path, symbol) in visited:
            continue
        if len(nodes) >= max_nodes:
            limited = True
            break
        visited.add((path, symbol))
        info = infos[path]
        start, end, _ = info['symbols'][symbol]
        nodes.append({'path': path, 'symbol': symbol, 'range': [start, end], 'depth': level,
                      'content_hash': versions[path],
                      'fully_displayed': displayed(path, start, end),
                      'chars': len(''.join(info['lines'][start - 1:end]))})
        if level == 0:
            for assignment in attribute_assignments(info, start, end):
                assignments.append({**assignment, 'path': path, 'symbol': symbol,
                                    'displayed': displayed(path, assignment['start_line'], assignment['end_line'])})
        if level >= depth:
            continue
        for other, target in sorted(linked_refs(info, start, end, symbol, aliases[path])):
            other = other or path
            if other not in infos:
                continue
            link = resolve_link(infos[other], target, aliases[other])
            if link is None or (other, link['symbol']) == (path, symbol):
                continue
            if len(edges) >= max_edges:
                limited = True
                continue
            binding = link['binding']
            edges.append({'from': [path, symbol], 'to': [other, link['symbol']], **link,
                          'binding_displayed': (displayed(other, *binding['binding_range']) if binding else None)})
            queue.append((other, link['symbol'], level + 1))
    return {'nodes': nodes, 'edges': edges, 'attribute_assignments': assignments, 'limited': limited,
            'limits': {'depth': depth, 'max_nodes': max_nodes, 'max_edges': max_edges},
            'scope': 'analysis only; nodes are not added to model evidence; not a runtime call graph'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, default=DATA / 'crossfile-candidates.json')
    parser.add_argument('--task', default='click-flag-envvar')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    case, _, checks, source, _ = admitted_case(args.admission.resolve(), args.catalog, args.task)
    output = args.output.resolve()
    if output.is_relative_to(source.resolve()) or output.is_relative_to(checks.resolve()):
        raise ValueError('Audit output must stay outside admitted sources and checks')
    output.mkdir(parents=True, exist_ok=False)
    workspace = source / 'before'
    original = digest(snapshot(workspace))
    allowed = sorted(path.relative_to(workspace).as_posix() for path in (workspace / 'src/click').rglob('*.py'))
    evidence = symbol_evidence(workspace, case['public_problem'], allowed, Events(output / 'trace.jsonl', 'link-audit'),
                               index_mode='symbols', query_policy='identifiers', packing_policy='dependency-reserve',
                               dependency_scope='full-seed')
    report = {'protocol': 'symbol-link-audit-v1', 'source_hash': original, 'implementation': implementation_metadata(),
              'model_calls': 0, 'description': case['public_problem'], 'evidence': evidence,
              'audit': audit(workspace, evidence, allowed)}
    if digest(snapshot(workspace)) != original:
        raise ValueError('Link audit mutated source')
    (output / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output / 'audit.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
