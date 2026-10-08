"""Hierarchical symbol/class retrieval using only description and original AST."""
import ast
from collections import Counter

from corecoder.retrieval.keyword import terms
from docs.experiments import function_index_audit_v1 as functions
from docs.experiments import symbol_directed_retrieval_v1 as symbols


def retrieve(index, description):
    """Promote resolved APIs and unique mentioned class scopes; reserve no extra budget."""
    # Qualified names are searchable metadata, never synthetic editable source.
    index.counts = [Counter(terms(c.path + '\n' + index.names[symbols.symbol_key(c)] + '\n' + c.content))
                    for c in index.chunks]
    index.document_frequency = Counter(term for count in index.counts for term in count)
    index.average_length = sum(sum(count.values()) for count in index.counts) / max(1, len(index.chunks)) or 1.0
    ranked = index.rank(description + ' contract contracts')
    scores = {symbols.symbol_key(c): score for score, c in ranked}
    direct, resolution = symbols.resolve_symbols(index, description)
    # A same-named class in two modules remains ambiguous; do not guess its owner.
    mentions = resolution['class_mentions']
    grouped = {}
    for item in mentions:
        grouped.setdefault(item['symbol'].rsplit('.', 1)[-1], []).append(item)
    owners = [(item['path'], item['symbol']) for candidates in grouped.values() if len(candidates) == 1
              for item in candidates]
    prioritized = []
    for chunk in index.chunks:
        key = symbols.symbol_key(chunk)
        name = index.names[key]
        owner = name.rsplit('.', 1)[0] if '.' in name else ''
        node = index.parsed[chunk.path]['symbols'][name][2]
        # Exclude nested local functions from the class-method scope.
        is_method = (chunk.path, owner) in owners and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        reason = 'qualified_symbol_bm25'
        priority = 0
        if is_method:
            priority = 2
            reason = 'mentioned_class_method'
            if name.rsplit('.', 1)[-1] == '__init__':
                priority = 3
                reason = 'mentioned_class_initializer'
        if key in direct:
            priority = 4 + direct[key]
            reason = 'explicit_function'
        prioritized.append((priority, scores.get(key, 0), chunk, reason))
    prioritized.sort(key=lambda row: (-row[0], -row[1], row[2].path, row[2].start_line, row[2].end_line))
    # Shared packer enforces <=6000 raw source chars and <=5 complete functions.
    packed = functions.pack(index, [(score, chunk) for _, score, chunk, _ in prioritized])
    reasons = {symbols.symbol_key(chunk): reason for _, _, chunk, reason in prioritized}
    for row in packed['evidence']:
        row['reason'] = reasons[(row['path'], row['start_line'], row['end_line'])]
    packed['metadata'].update(policy='class-scoped-v1', class_scopes=[{'path': p, 'symbol': n} for p, n in owners],
                              resolution=resolution,
                              ranking='explicit APIs > unique class initializer > class methods > qualified-name BM25')
    return packed
