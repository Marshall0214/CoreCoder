"""Experimental compact packing over frozen evidence; no retrieval or model calls."""

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from docs.experiments.staged_evidence_coverage_v1 import covered_lines, public_anchors
from evals.real_admission import DATA
from evals.real_suite import file_hash, load_manifest
from evals.schema import RunConfig, relative_path
from evals.staged_repair import select_evidence, validate_localization


def docstring_ranges(raw):
    """Only standalone complete AST docstring statements; preserve other strings."""
    try:
        tree = ast.parse(raw.decode('utf-8'))
    except SyntaxError:
        return [], 'syntax-error-retained'
    lines = raw.splitlines(keepends=True)
    ranges = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) or not node.body:
            continue
        statement = node.body[0]
        if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)):
            continue
        # AST offsets are UTF-8 byte offsets. A same-line def or semicolon sibling
        # must never disappear with a string expression.
        if (lines[statement.lineno - 1][:statement.col_offset].strip()
                or lines[statement.end_lineno - 1][statement.end_col_offset:].strip()):
            continue
        ranges.append((statement.lineno, statement.end_lineno))
    return ranges, 'valid'


def consecutive_runs(numbers):
    result = []
    for number in sorted(numbers):
        if result and number == result[-1][1] + 1:
            result[-1][1] = number
        else:
            result.append([number, number])
    return result


def compact_evidence(reads, seeds, sources, max_chars):
    """Keep read-first order and atomic candidate admission; emit source-exact runs."""
    if type(max_chars) is not int or max_chars < 0:
        raise ValueError('Character limit must be a nonnegative integer')
    rows = reads + seeds
    parsed, removed, available = {}, {}, {}
    for row in rows:
        path = row['path']
        if path not in sources:
            raise ValueError('Missing candidate source')
        if path not in parsed:
            raw = sources[path]
            if not isinstance(raw, bytes):
                raise ValueError('Sources must preserve raw bytes')
            ranges, status = docstring_ranges(raw)
            parsed[path] = (raw.decode('utf-8').splitlines(keepends=True),
                            hashlib.sha256(raw).hexdigest(), ranges, status)
            available[path] = set()
        lines, version, _, _ = parsed[path]
        start, end = row['start_line'], row['end_line']
        if (type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines)
                or row['content_hash'] != version
                or row['content'] not in {''.join(lines[start - 1:end]),
                                         '\n'.join(line.rstrip('\r\n') for line in lines[start - 1:end])}):
            raise ValueError('Candidate version or source text mismatch')
        available[path].update(range(start, end + 1))
    for path, (_, _, ranges, _) in parsed.items():
        removed[path] = {line for start, end in ranges
                         if set(range(start, end + 1)) <= available[path]
                         for line in range(start, end + 1)}
    selected, decisions, used, shown = [], [], 0, {path: set() for path in parsed}
    for index, row in enumerate(rows):
        path = row['path']
        lines, version, _, _ = parsed[path]
        span = set(range(row['start_line'], row['end_line'] + 1))
        remaining = span - removed[path] - shown[path]
        fragments = [{'path': path, 'content_hash': version, 'start_line': start, 'end_line': end,
                      'content': ''.join(lines[start - 1:end]), 'reason': 'compact_read_first',
                      'origin_candidate': index, 'origin_range': [row['start_line'], row['end_line']]}
                     for start, end in consecutive_runs(remaining)]
        cost = sum(len(fragment['content']) for fragment in fragments)
        decision = ('redundant_or_docstring' if not fragments else
                    'remaining_capacity' if used + cost > max_chars else 'selected')
        if decision == 'selected':
            selected.extend(fragments)
            used += cost
            shown[path].update(remaining)
        decisions.append({'candidate': index, 'path': path, 'range': [row['start_line'], row['end_line']],
                          'decision': decision, 'new_chars': cost, 'new_lines': len(remaining),
                          'docstring_lines': len(span & removed[path]),
                          'already_shown_lines': len(span & shown[path]) if decision != 'selected'
                          else len(span - removed[path] - remaining)})
    return selected, {'policy': 'compact-read-first-v1', 'max_chars': max_chars, 'selected_chars': used,
                      'selected_fragments': len(selected), 'decisions': decisions,
                      'removed_docstring_lines': {path: sorted(lines) for path, lines in removed.items()},
                      'parse_status': {path: values[3] for path, values in parsed.items()}}


def comparison(description, sources, pool, limit, bare_names=()):
    compact, metadata = compact_evidence(pool['reads'], pool['seeds'], sources, limit)
    baseline = select_evidence(pool['reads'], pool['seeds'], limit)
    text = {path: raw.decode('utf-8') for path, raw in sources.items()}
    anchors = public_anchors(description, text, bare_names)
    coverage = []
    for anchor in anchors:
        path = anchor['path']
        docs, _ = docstring_ranges(sources[path])
        # Code-span metric omits docstrings in both arms, including pool-missing
        # docstrings; it is not a semantic relevance or patch-success measure.
        doc_lines = {line for start, end in docs for line in range(start, end + 1)}
        target = set(range(anchor['start_line'], anchor['end_line'] + 1)) - doc_lines
        coverage.append({**anchor, 'non_docstring_lines': len(target),
                         'pool_lines': len(target & covered_lines(pool['reads'] + pool['seeds'], path)),
                         'baseline_lines': len(target & covered_lines(baseline, path)),
                         'compact_lines': len(target & covered_lines(compact, path))})
    return {'baseline_chars': sum(len(row['content']) for row in baseline), 'compact': metadata,
            'coverage': coverage, 'fragments': compact,
            'baseline_payload_chars': len(json.dumps(baseline, ensure_ascii=False)),
            'compact_payload_chars': len(json.dumps(compact, ensure_ascii=False))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', required=True, metavar='SOURCE=PATH')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    roots = {}
    for item in args.source:
        name, separator, path = item.partition('=')
        if not separator or not path or name in roots:
            parser.error('Supply unique SOURCE=PATH directories')
        roots[name] = Path(path).resolve()
    protocol_path = DATA / 'staged-shared-repeat-v1.json'
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    manifest = DATA / relative_path(protocol['manifest'])
    if file_hash(manifest) != protocol['manifest_sha256']:
        raise ValueError('Frozen manifest changed')
    data, entries = load_manifest(manifest)
    if set(roots) != {name for name, _, _ in entries}:
        raise ValueError('Supply all frozen source groups')
    output = args.output.resolve()
    checkpoints = [ROOT / relative_path(record['path']) for record in protocol['checkpoints'].values()]
    if output.exists() or any(output.is_relative_to(path) for path in
                              [*roots.values(), *(path.parent.resolve() for path in checkpoints)]):
        raise ValueError('Use a fresh output outside sources and checkpoints')
    tasks = []
    for name, catalog, task in entries:
        record = protocol['checkpoints'][task]
        path = ROOT / relative_path(record['path'])
        if not path.resolve().is_relative_to(ROOT) or file_hash(path) != record['sha256']:
            raise ValueError('Frozen checkpoint changed')
        checkpoint = json.loads(path.read_text(encoding='utf-8'))
        cases = json.loads(catalog.read_text(encoding='utf-8'))['cases']
        description = next(case['public_problem'] for case in cases if case['case_id'] == task)
        workspace = roots[name] / task / 'before'
        validate_localization(checkpoint, workspace, description, checkpoint['allowed_files'], RunConfig(**data['config']))
        sources = {file: (workspace / relative_path(file)).read_bytes() for file in checkpoint['allowed_files']}
        result = comparison(description, sources, checkpoint['pool'], data['config']['search_max_chars'],
                            ('prompt', 'confirm') if task == 'click-prompt-suffix' else ())
        tasks.append({'task_id': task, 'checkpoint_sha256': file_hash(path),
                      'candidate_pool_hash': checkpoint['localization_result']['candidate_pool_hash'], **result})
    report = {'purpose': 'offline-compact-packing-v1', 'model_calls': 0, 'benchmark_eligible': False,
              'implementation_sha256': protocol['implementation_sha256'],
              'packing_sha256': file_hash(Path(__file__)), 'protocol_sha256': file_hash(protocol_path),
              'tasks': tasks, 'limitations': 'Offline coverage only; no repair success or token savings claim. '
              'Full before source classifies docstrings, but output lines must come from frozen candidates. '
              'Fragment metadata and JSON overhead are measured separately from the 6000-character evidence cap.'}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'packing.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for task in tasks:
        print(task['task_id'], task['baseline_chars'], '->', task['compact']['selected_chars'],
              'payload', task['baseline_payload_chars'], '->', task['compact_payload_chars'])
    print(output / 'packing.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
