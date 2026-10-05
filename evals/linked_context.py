"""Optional budgeted packing of assignment windows and constructor-alias bundles."""

import ast
import hashlib

from corecoder.retrieval.keyword import terms

from .symbol_context import module_name, parse_source
from .symbol_index import expand_query
from .symbol_link_audit import audit


def repack(workspace, description, allowed_files, evidence, events, max_chars=6000):
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or not 256 <= max_chars <= 20000:
        raise ValueError('Invalid linked context budget')
    workspace = workspace.resolve()
    graph = audit(workspace, evidence, allowed_files)
    modules = {module_name(name): name for name in allowed_files}
    infos = {}
    versions = {node['path']: node['content_hash'] for node in graph['nodes']}
    for name, version in versions.items():
        path = workspace / name
        if not path.resolve().is_relative_to(workspace) or any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError('Linked source path escaped workspace')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != version:
            raise ValueError('Linked source version changed')
        infos[name] = parse_source(name, data, modules)
    selected, discarded, accepted, used = [], [], [], 0

    def fragment(path, symbol, start, end, reason):
        info = infos[path]
        a, b, _ = info['symbols'][symbol]
        return {'path': path, 'symbol': symbol, 'start_line': start, 'end_line': end,
                'symbol_range': [a, b], 'complete_symbol': start == a and end == b,
                'content_hash': versions[path], 'content': ''.join(info['lines'][start - 1:end]),
                'depth': 1, 'reason': reason, 'parse_status': 'valid'}

    def add(rows, label):
        nonlocal used
        pending = []
        for row in rows:
            existing = selected + pending
            if any(old['path'] == row['path'] and old['start_line'] <= row['start_line']
                   and row['end_line'] <= old['end_line'] for old in existing):
                continue
            if any(old['path'] == row['path'] and old['start_line'] <= row['end_line']
                   and row['start_line'] <= old['end_line'] for old in existing):
                discarded.append({'candidate': label, 'reason': 'overlap'})
                return False
            pending.append(row)
        cost = sum(len(row['content']) for row in pending)
        if used + cost > max_chars or len(selected) + len(pending) > 20:
            discarded.append({'candidate': label, 'reason': 'budget', 'chars': cost,
                              'available_chars': max_chars - used})
            return False
        selected.extend(pending)
        used += cost
        accepted.append({'candidate': label, 'added_chars': cost})
        return True

    query_terms = set(terms(expand_query(description, 'identifiers')))
    # Preserve complete keyword seeds first. Replace a partial seed only when
    # a query-related assignment window can be supplied; no symbol names are hardcoded.
    for row in evidence:
        if row['reason'] != 'keyword':
            continue
        if row['complete_symbol']:
            add([row], [row['path'], row['symbol'], 'keyword'])
            continue
        assignments = [item for item in graph['attribute_assignments']
                       if item['path'] == row['path'] and item['symbol'] == row['symbol']]
        ranked = sorted(assignments, key=lambda item: (
            -len(query_terms & set(terms(item['expression'] + ' ' + item['attribute']))),
            -int(item['value_is_call']), item['start_line']))
        chosen = next((item for item in ranked if query_terms & set(terms(item['expression'] + ' ' + item['attribute']))), None)
        if chosen:
            a, b = row['symbol_range']
            window = fragment(row['path'], row['symbol'], max(a, chosen['start_line'] - 4),
                              min(b, chosen['end_line'] + 4), 'query-assignment-window')
            if add([window], [row['path'], row['symbol'], 'assignment']):
                continue
        add([row], [row['path'], row['symbol'], 'partial-keyword'])

    bundles = []
    for edge in graph['edges']:
        if edge['binding'] is None:
            continue
        path, owner = edge['from']
        target_path, target = edge['to']
        if path not in infos or target_path not in infos:
            continue
        _, _, node = infos[path]['symbols'][owner]
        occurrences = sum(isinstance(item, ast.Name) and item.id == edge['alias'] for item in ast.walk(node))
        relevance = len(query_terms & set(terms(edge['alias'] + ' ' + target)))
        bundles.append((-relevance, -occurrences, path, owner, target_path, target, edge))
    for _, _, path, owner, target_path, target, edge in sorted(bundles, key=lambda item: item[:6]):
        a, b, _ = infos[path]['symbols'][owner]
        x, y, _ = infos[target_path]['symbols'][target]
        c, d = edge['binding']['binding_range']
        binding = fragment(target_path, target, c, d, 'constructor-binding')
        # Binding is outside the class; metadata identifies it as a module window.
        binding.update(symbol='<module-binding>', symbol_range=[c, d], complete_symbol=False)
        add([fragment(path, owner, a, b, 'alias-owner'), binding,
             fragment(target_path, target, x, y, 'constructor-target')],
            [path, owner, edge['alias'], target])
    for row in evidence:
        add([row], [row['path'], row['symbol'], 'fallback'])
    events.emit('linked_context_packed', max_chars=max_chars, evidence_chars=used,
                audit_limited=graph['limited'], accepted=accepted, discarded=discarded,
                selected=[{key: value for key, value in row.items() if key != 'content'} for row in selected])
    return selected
