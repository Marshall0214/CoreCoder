"""Public-anchor balanced selection of exact source intervals from a frozen pool."""
import hashlib

from docs.experiments.staged_compact_packing_v1 import consecutive_runs
from docs.experiments.staged_evidence_coverage_v1 import public_anchors


def balanced_evidence(reads, seeds, sources, description, max_chars, bare_names=()):
    if type(max_chars) is not int or max_chars < 0:
        raise ValueError('Character budget must be a nonnegative integer')
    rows = reads + seeds
    parsed, available = {}, {}
    for row in rows:
        path = row['path']
        if path not in sources or not isinstance(sources[path], bytes):
            raise ValueError('Missing raw candidate source')
        if path not in parsed:
            raw = sources[path]
            parsed[path] = (raw.decode('utf-8').splitlines(), hashlib.sha256(raw).hexdigest(), raw.decode('utf-8').splitlines(keepends=True))
            available[path] = set()
        lines, version, physical = parsed[path]
        start, end = row['start_line'], row['end_line']
        if (type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines)
                or row['content_hash'] != version or row['content'] not in
                {'\n'.join(lines[start-1:end]), ''.join(physical[start-1:end])}):
            raise ValueError('Candidate source/version mismatch')
        available[path].update(range(start, end+1))
    anchors = public_anchors(description, {p: sources[p].decode('utf-8') for p in parsed}, bare_names)
    definitions = [a for a in anchors if a['kind'] == 'definition' and
                   set(range(a['start_line'], a['end_line']+1)) & available[a['path']]]
    groups = []
    for anchor in definitions:
        path, start, end = anchor['path'], anchor['start_line'], anchor['end_line']
        # Header first, then neighborhoods of explicit public identifiers, then all remaining lines.
        windows = [(start, min(end, start+11))]
        for item in anchors:
            if item['kind'] == 'identifier' and item['path'] == path and start <= item['start_line'] <= end:
                line = item['start_line']
                windows.append((max(start, line-4), min(end, line+4)))
        windows.extend((n, min(end, n+11)) for n in range(start, end+1, 12))
        groups.append((anchor['name'], path, windows))
    if not groups:
        # Descriptions without explicit API names still get round-robin candidate coverage.
        groups = [(f'candidate-{i}', r['path'], [(n, min(r['end_line'], n+11))
                   for n in range(r['start_line'], r['end_line']+1, 12)]) for i, r in enumerate(rows)]
    # Retain non-anchor helpers as a final round-robin group rather than requiring an oracle.
    groups.append(('candidate-fallback', None, [(r['path'], n, min(r['end_line'], n+11))
                  for r in rows for n in range(r['start_line'], r['end_line']+1, 12)]))
    shown = {p: set() for p in parsed}
    decisions, used = [], 0

    def rendered_cost(state):
        return sum(len('\n'.join(parsed[p][0][a-1:b])) for p, numbers in state.items() for a, b in consecutive_runs(numbers))

    rounds = max((len(g[2]) for g in groups), default=0)
    for index in range(rounds):
        for name, path, windows in groups:
            if index >= len(windows):
                continue
            if path is None:
                current, start, end = windows[index]
            else:
                current, (start, end) = path, windows[index]
            new = set(range(start, end+1)) & available[current] - shown[current]
            if not new:
                continue
            proposed = {p: numbers | new if p == current else numbers for p, numbers in shown.items()}
            cost = rendered_cost(proposed)
            selected = cost <= max_chars
            decisions.append({'group': name, 'path': current, 'range': [start, end], 'new_lines': len(new),
                              'decision': 'selected' if selected else 'budget', 'proposed_chars': cost})
            if selected:
                shown, used = proposed, cost
    evidence = [{'path': p, 'content_hash': parsed[p][1], 'start_line': a, 'end_line': b,
                 'content': '\n'.join(parsed[p][0][a-1:b]), 'reason': 'public-balanced-interval'}
                for p, numbers in sorted(shown.items()) for a, b in consecutive_runs(numbers)]
    coverage = []
    for a in definitions:
        span = set(range(a['start_line'], a['end_line']+1))
        displayed = span & shown[a['path']]
        coverage.append({**a, 'visible_lines': len(displayed), 'complete': displayed == span,
                         'missing_ranges': consecutive_runs(span - displayed)})
    return evidence, {'content_chars': used, 'limit_chars': max_chars, 'decisions': decisions,
                      'definition_coverage': coverage, 'source_lines_added': 0,
                      'limitations': 'Public anchors are lexical cues, not guaranteed repair locations. '
                                     'Partial ranges are separate exact fragments; omitted docs are budget omissions, not stripped text.'}
