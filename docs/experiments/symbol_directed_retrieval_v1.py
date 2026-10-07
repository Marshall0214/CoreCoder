"""Public description identifiers prioritize complete functions over the same BM25 corpus."""

import ast
import json
import re
from pathlib import Path

from docs.experiments import function_index_audit_v1 as retrieval
from docs.experiments import function_index_repair_v1 as repair
from evals.symbol_context import module_name

POLICIES = ('direct-functions', 'symbol-directed-functions')
IDENTIFIER = re.compile(r'(?<![\w.])[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*')


def symbol_key(chunk):
    return chunk.path, chunk.start_line, chunk.end_line


def explicit_mentions(description):
    """Bare names need code syntax or a requirement-subject position, not just vocabulary overlap."""
    accepted = []
    for match in IDENTIFIER.finditer(description):
        name = match.group()
        tail = description[match.end():]
        quoted = match.start() > 0 and description[match.start() - 1] == '`' and tail.startswith('`')
        call = re.match(r'\s*\(', tail)
        subject = re.match(r'(?:(?:\s+(?:and|or)\s+|,\s*)[A-Za-z_]\w*)*\s+(?:must|should|shall)\b', tail)
        if '.' in name or '_' in name or quoted or call or subject:
            accepted.append(name)
    return list(dict.fromkeys(accepted))


def resolve_symbols(index, description):
    """No labels, imports from executing source, approximate names, or guessed constructors."""
    identifiers = list(dict.fromkeys(m.group() for m in IDENTIFIER.finditer(description)))
    explicit = explicit_mentions(description)
    classes = {(path, name) for path, info in index.parsed.items() for name, (_, _, node) in info['symbols'].items()
               if isinstance(node, ast.ClassDef)}

    def qualified(path, name, identifier):
        full_name = module_name(path) + '.' + name
        return name == identifier or full_name == identifier or full_name.endswith('.' + identifier)

    mentioned_classes = {(path, name) for path, name in classes for identifier in identifiers
                         if (qualified(path, name, identifier) if '.' in identifier else name.rsplit('.', 1)[-1] == identifier)}
    matches, priorities = [], {}
    for identifier in explicit:
        dotted = '.' in identifier
        candidates = [key for key, name in index.names.items()
                      if (qualified(key[0], name, identifier) if dotted else name.rsplit('.', 1)[-1] == identifier)]
        reason = 'qualified' if dotted else 'bare'
        if len(candidates) > 1 and not dotted:
            scoped = [key for key in candidates if any(path == key[0] and index.names[key].startswith(owner + '.')
                                                      for path, owner in mentioned_classes)]
            if scoped:
                candidates, reason = scoped, 'class-scoped-bare'
        if not candidates:
            is_class = any(qualified(path, name, identifier) if dotted else name.rsplit('.', 1)[-1] == identifier
                           for path, name in mentioned_classes)
            if not is_class:
                matches.append({'identifier': identifier, 'resolution': 'unresolved', 'candidates': []})
            continue
        rows = [{'path': key[0], 'symbol': index.names[key], 'start_line': key[1], 'end_line': key[2]}
                for key in sorted(candidates)]
        resolution = 'resolved' if len(candidates) == 1 else 'ambiguous'
        matches.append({'identifier': identifier, 'resolution': resolution, 'reason': reason, 'candidates': rows})
        if resolution == 'resolved':
            key = candidates[0]
            priorities[key] = max(priorities.get(key, 0), 2 if dotted else 1)
    return priorities, {'identifiers': explicit, 'class_mentions': [{'path': p, 'symbol': n}
            for p, n in sorted(mentioned_classes)], 'matches': matches,
            'resolved_symbols': [{'path': k[0], 'symbol': index.names[k], 'start_line': k[1], 'end_line': k[2]}
                                 for k in sorted(priorities)]}


def rank(index, query, description):
    baseline = index.rank(query)
    priorities, metadata = resolve_symbols(index, description)
    scores = {symbol_key(chunk): score for score, chunk in baseline}
    chunks = {symbol_key(chunk): chunk for _, chunk in baseline}
    chunks.update({symbol_key(chunk): chunk for chunk in index.chunks if symbol_key(chunk) in priorities})
    keys = sorted(chunks, key=lambda key: (-priorities.get(key, 0), -scores.get(key, 0), key[0], key[1], key[2]))
    return [(scores.get(key, 0), chunks[key]) for key in keys], metadata


def coverage(packed, metadata):
    targets = metadata['resolved_symbols']
    covered = [target for target in targets if any(row['path'] == target['path']
               and row['start_line'] <= target['start_line'] and row['end_line'] >= target['end_line']
               for row in packed['evidence'])]
    return {'resolved': len(targets), 'covered': len(covered),
            'recall': len(covered) / len(targets) if targets else None,
            'missing': [t for t in targets if t not in covered],
            'scope': 'unambiguously resolved explicit function mentions; no reference-patch labels'}


def observe(case):
    index = retrieval.FunctionIndex(case['before'], case['allowed_files'])
    metadata = index.refresh()
    query = case['description'] + ' contract contracts'
    directed, resolution = rank(index, query, case['description'])
    baseline = retrieval.pack(index, index.rank(query))
    candidate = retrieval.pack(index, directed)
    policies = {POLICIES[0]: baseline, POLICIES[1]: candidate}
    for packed in policies.values():
        repair.validate_evidence(case['before'], case['allowed_files'], packed['evidence'])
        packed['explicit_symbol_coverage'] = coverage(packed, resolution)
    if repair.digest(repair.snapshot(case['before'])) != case['before_hash']:
        raise ValueError('Source changed during retrieval')
    return {'task_id': case['task_id'], 'query': query, 'index': metadata, 'resolution': resolution, 'policies': policies,
            'directed_rankings': [{'path': c.path, 'symbol': index.names[symbol_key(c)],
                                  'start_line': c.start_line, 'end_line': c.end_line, 'bm25_score': score}
                                 for score, c in directed]}


def observe_all(cases, output):
    observations = [observe(case) for case in cases]
    Path(output, 'observations.json').write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding='utf-8')
    return observations
