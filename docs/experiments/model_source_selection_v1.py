"""Model-selected AST source fragments; no reference patches or graders are read."""
import ast
import hashlib
import json
from pathlib import Path

from corecoder.retrieval.keyword import terms
from evals.schema import relative_path
from evals.symbol_context import parse_source


def inventory(workspace, allowed):
    rows = []
    workspace = Path(workspace).resolve()
    for name in sorted(set(allowed)):
        relative_path(name)
        path = workspace / name
        if path.is_symlink() or not path.resolve().is_relative_to(workspace):
            raise ValueError('Source outside allowed workspace')
        data = path.read_bytes()
        parsed = parse_source(name, data, {})
        for symbol, (start, end, node) in parsed['symbols'].items():
            # Classes are represented by their individual methods, avoiding huge containers.
            if isinstance(node, ast.ClassDef):
                continue
            signature = symbol + '(' + ast.unparse(node.args) + ')'
            rows.append({'id': name + ':' + symbol, 'path': name, 'symbol': symbol,
                         'signature': signature[:220], 'doc': (ast.get_docstring(node) or '')[:180],
                         'start_line': start, 'end_line': end,
                         'content_hash': hashlib.sha256(data).hexdigest(),
                         'content': ''.join(parsed['lines'][start - 1:end])})
    return rows


def overview(rows, description, seeds, limit=7000):
    words = set(terms(description))
    seed_ids = {r['path'] + ':' + r['symbol'] for r in seeds}
    ranked = sorted(rows, key=lambda r: (
        -(r['id'] in seed_ids), -len(words & set(terms(r['signature'] + ' ' + r['doc']))), r['id']))
    shown, size = [], 0
    for row in ranked:
        item = {k: row[k] for k in ('id', 'signature', 'doc')}
        cost = len(json.dumps(item, ensure_ascii=False))
        if size + cost > limit:
            continue
        shown.append(item)
        size += cost
    return shown


def pack(rows, selected):
    if not isinstance(selected, list) or not 1 <= len(selected) <= 5:
        raise ValueError('Select one to five symbol IDs')
    if any(not isinstance(v, str) for v in selected) or len(set(selected)) != len(selected):
        raise ValueError('Require unique string IDs')
    lookup = {r['id']: r for r in rows}
    if any(v not in lookup for v in selected):
        raise ValueError('Unknown selected symbol')
    evidence, used = [], 0
    for identifier in selected:
        row = dict(lookup[identifier])
        lines = row['content'].splitlines(keepends=True)
        kept = []
        for line in lines:
            if used + len(line) > 6000:
                break
            kept.append(line)
            used += len(line)
        if not kept:
            continue
        row.update(content=''.join(kept), end_line=row['start_line'] + len(kept) - 1,
                   complete_symbol=len(kept) == len(lines), reason='model_selected')
        evidence.append(row)
    if not evidence:
        raise ValueError('No selected source fits the evidence budget')
    return evidence


def select(llm, job, events):
    rows = inventory(job['workspace'], job['allowed_files'])
    shown = overview(rows, job['description'], job['evidence'])
    messages = [
        {'role': 'system', 'content': 'Select the Python functions needed to diagnose and repair the described defect. '
         'Return JSON exactly {"symbols":["id", ...]}. Select 1 to 5 IDs from the supplied overview, '
         'most important first. Include callers or state initialization when relevant. Do not generate a patch.'},
        {'role': 'user', 'content': json.dumps({'description': job['description'], 'symbols': shown}, ensure_ascii=False)}]
    root = events.path.parent
    (root / 'selection-messages.json').write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding='utf-8')
    response = llm.chat(messages, tools=[])
    (root / 'selection-response.txt').write_text(events.clean(response.content), encoding='utf-8')
    if response.tool_calls:
        raise ValueError('Selection cannot call tools')
    parsed = json.loads(response.content)
    if not isinstance(parsed, dict) or set(parsed) != {'symbols'}:
        raise ValueError('Invalid selection JSON')
    shown_ids = {r['id'] for r in shown}
    if not isinstance(parsed['symbols'], list) or any(v not in shown_ids for v in parsed['symbols']):
        raise ValueError('Selection must use displayed IDs')
    evidence = pack(rows, parsed['symbols'])
    events.emit('source_selection', selected=parsed['symbols'], overview_symbols=len(shown),
                evidence_chars=sum(len(r['content']) for r in evidence))
    return evidence


def refresh(workspace, allowed, seeds):
    return pack(inventory(workspace, allowed), [r['path'] + ':' + r['symbol'] for r in seeds])
