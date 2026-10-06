"""Public-only function BM25 retrieval and bounded evidence audit on Click."""

import argparse
import ast
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import mean

from corecoder.retrieval.keyword import terms
from docs.experiments import real_retrieval_audit_v1 as audit
from docs.experiments.retrieved_function_repair_v1 import OBS_SHA, prepare
from evals.runner import digest, snapshot
from evals.symbol_context import dependency_refs, module_name, parse_source
from evals.symbol_index import PythonCodeIndex

POLICIES = ('raw-chunks', 'chunk-functions', 'python-line-chunks', 'direct-functions', 'direct-functions-deps')


class FunctionIndex(PythonCodeIndex):
    """Reuse AST symbol corpora and BM25; retain complete functions/methods only."""

    def __init__(self, workspace, allowed):
        super().__init__(workspace, allowed, 'symbols')
        self.parsed = {}
        self.names = {}

    def refresh(self):
        metadata = super().refresh()
        modules = {module_name(path): path for path in sorted(self.allowed_sources)}
        self.parsed, self.names = {}, {}
        versions = {c.path: c.content_hash for c in self.chunks}
        for path, version in sorted(versions.items()):
            data = (self.workspace / path).read_bytes()
            if hashlib.sha256(data).hexdigest() != version:
                raise ValueError('Source changed during function indexing')
            info = parse_source(path, data, modules)
            info['hash'] = version
            self.parsed[path] = info
            for name, (start, end, node) in info['symbols'].items():
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.names[(path, start, end)] = name
        self.chunks = [c for c in self.chunks if (c.path, c.start_line, c.end_line) in self.names]
        self.counts = [Counter(terms(c.path + '\n' + c.content)) for c in self.chunks]
        self.document_frequency = Counter(term for count in self.counts for term in count)
        self.average_length = sum(sum(count.values()) for count in self.counts) / max(1, len(self.chunks)) or 1.0
        metadata.update(mode='functions-only', chunks=len(self.chunks),
                        parse_failures=sorted(p for p, i in self.parsed.items() if i['tree'] is None))
        metadata['index_hash'] = hashlib.sha256(('functions-only:' + metadata['source_hash']).encode()).hexdigest()
        return metadata


def pack(index, ranked, depth=0, limit=6000, top_k=5):
    if depth not in (0, 1) or limit <= 0 or top_k <= 0:
        raise ValueError('Invalid function packing limits')
    selected, discarded, seeds = [], [], []
    used = 0

    def append(path, name, start, end, rank, score, reason):
        nonlocal used
        if any(r['path'] == path and r['start_line'] <= end and r['end_line'] >= start for r in selected):
            discarded.append({'path': path, 'symbol': name, 'rank': rank, 'reason': 'overlap'})
            return False
        info = index.parsed[path]
        content = ''.join(info['lines'][start - 1:end])
        if used + len(content) > limit:
            discarded.append({'path': path, 'symbol': name, 'rank': rank, 'reason': 'budget', 'chars': len(content)})
            return False
        selected.append({'path': path, 'symbol': name, 'start_line': start, 'end_line': end,
                         'content': content, 'content_hash': info['hash'], 'rank': rank,
                         'score': score, 'reason': reason, 'complete_symbol': True})
        used += len(content)
        return True

    for rank, (score, chunk) in enumerate(ranked, 1):
        if len(seeds) == top_k:
            break
        name = index.names[(chunk.path, chunk.start_line, chunk.end_line)]
        if append(chunk.path, name, chunk.start_line, chunk.end_line, rank, score, 'function_seed'):
            seeds.append((chunk.path, name, chunk.start_line, chunk.end_line, rank, score))
    if depth:
        for path, name, start, end, rank, score in seeds:
            for other, target in sorted(dependency_refs(index.parsed[path], start, end, name)):
                other = other or path
                info = index.parsed.get(other)
                if not info or target not in info['symbols']:
                    continue
                begin, finish, node = info['symbols'][target]
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or len(selected) >= 20:
                    continue
                append(other, target, begin, finish, rank, score, 'static_function_dependency')
    return {'evidence': selected, 'metadata': {'evidence_chars': used, 'max_chars': limit,
            'seed_count': len(seeds), 'max_seeds': top_k, 'dependency_depth': depth,
            'discarded': discarded, 'oversized_fallback': 'none'}}


def observe(case, prior):
    index = FunctionIndex(case['before'], case['allowed_files'])
    metadata = index.refresh()
    ranked = index.rank(prior['query'])
    lines = PythonCodeIndex(case['before'], case['allowed_files'], 'lines')
    line_metadata = lines.refresh()
    if line_metadata['source_hash'] != metadata['source_hash']:
        raise ValueError('Python line and function source corpora differ')
    line_ranked = lines.rank(prior['query'])
    line_packing = audit.bounded_chunks(line_ranked)
    if digest(snapshot(case['before'])) != case['before_hash']:
        raise ValueError('Before source changed during audit')
    return {'task_id': case['task_id'], 'query': prior['query'], 'index': metadata, 'line_index': line_metadata,
            'line_rankings': [{'path': c.path, 'start_line': c.start_line, 'end_line': c.end_line,
                              'content_hash': c.content_hash, 'score': score} for score, c in line_ranked],
            'function_rankings': [{'path': c.path, 'start_line': c.start_line, 'end_line': c.end_line,
                                   'symbol': index.names[(c.path, c.start_line, c.end_line)],
                                   'content_hash': c.content_hash, 'score': score} for score, c in ranked],
            'policies': {'python-line-chunks': {'evidence': line_packing['selected'],
                                               'metadata': {k: v for k, v in line_packing.items() if k != 'selected'}},
                         'direct-functions': pack(index, ranked),
                         'direct-functions-deps': pack(index, ranked, depth=1)}}


def evaluate(cases, bundles, priors, output):
    output = output.resolve()
    if output.exists() or any(output.is_relative_to(c['before'].parent.resolve()) for c in cases):
        raise ValueError('Use fresh output outside admitted sources')
    expected = [c['task_id'] for c in cases]
    if expected != [p['task_id'] for p in priors] or expected != [b['task_id'] for b in bundles]:
        raise ValueError('Task order mismatch')
    if any(p['query'] != c['description'] + ' contract contracts' for c, p in zip(cases, priors)):
        raise ValueError('Public query changed')
    output.mkdir(parents=True)
    protocol = {'protocol': 'function-index-audit-v1', 'development_only': True, 'benchmark_eligible': False,
                'engine_hash': audit.ENGINE, 'source_observations_sha256': OBS_SHA,
                'policies': list(POLICIES), 'query': 'unchanged public_problem + literal contract contracts',
                'max_chars': 6000, 'max_seeds': 5, 'dependency_depths': [0, 1],
                'bm25': {'k1': 1.2, 'b': 0.75, 'query_terms': 'unique'},
                'adapter_sha256': audit.sha(Path(__file__)),
                'reused_symbol_index_sha256': audit.sha(audit.ROOT / 'evals/symbol_index.py'),
                'reused_function_mapping_sha256': audit.sha(audit.ROOT / 'docs/experiments/retrieved_functions_v1.py'),
                'corpus_control': 'Python lines and functions share source_hash; original chunk baselines also contain Markdown',
                'inputs': [{k: str(v) if isinstance(v, Path) else v for k, v in c.items()} for c in cases]}
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    observations = []
    for case, bundle, prior in zip(cases, bundles, priors):
        observed = observe(case, prior)
        observed['policies'].update({'raw-chunks': bundle['policies']['raw-chunks'],
                                     'chunk-functions': bundle['policies']['functions']})
        observations.append(observed)
    # Commit ALL retrieval/packing choices to disk before reading any reference labels.
    path = output / 'observations.json'
    path.write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = []
    for case, observation in zip(cases, observations):
        targets, spans = audit.labels(case)
        rows.append({'task_id': case['task_id'], 'scores': {
            policy: {'changed_line_recall': audit.span_recall(observation['policies'][policy]['evidence'], spans),
                     'evidence_chars': sum(len(r['content']) for r in observation['policies'][policy]['evidence']),
                     'target_file_recall': len(set(targets) & {r['path'] for r in observation['policies'][policy]['evidence']}) / len(targets)}
            for policy in POLICIES}})
    if any(digest(snapshot(c['before'])) != c['before_hash'] for c in cases):
        raise ValueError('Before source changed during scoring')
    summary = {p: {key: mean(r['scores'][p][key] for r in rows) for key in rows[0]['scores'][p]} for p in POLICIES}
    result = {'protocol': protocol, 'complete': True, 'repair_llm_calls': 0, 'embedding_calls': 0,
              'observations_sha256': audit.sha(path), 'summary': summary, 'rows': rows,
              'limitations': '7 Click development cases; changed-line proxy is not repair success; function-only corpus omits module/class non-function code and skips oversized symbols without fallback'}
    (output / 'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases, bundles = prepare(args.source.resolve(), args.output.resolve())
    priors = json.loads((args.source / 'observations.json').read_text(encoding='utf-8'))
    evaluate(cases, bundles, priors, args.output)


if __name__ == '__main__':
    main()
