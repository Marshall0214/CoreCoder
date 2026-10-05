"""Offline original versus linked-bundle context comparison at the same budget."""

import argparse
import json
from pathlib import Path

from .linked_context import repack
from .real_admission import DATA
from .real_tasks import admitted_case
from .runner import digest, implementation_metadata, snapshot
from .runtime import Events
from .symbol_context import symbol_evidence


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
        raise ValueError('Output must stay outside admitted sources and checks')
    output.mkdir(parents=True, exist_ok=False)
    workspace = source / 'before'
    original = digest(snapshot(workspace))
    allowed = sorted(path.relative_to(workspace).as_posix() for path in (workspace / 'src/click').rglob('*.py'))
    base = symbol_evidence(workspace, case['public_problem'], allowed, Events(output / 'base.jsonl', 'base'),
                           index_mode='symbols', query_policy='identifiers', packing_policy='dependency-reserve',
                           dependency_scope='full-seed')
    linked = repack(workspace, case['public_problem'], allowed, base, Events(output / 'linked.jsonl', 'linked'))
    if digest(snapshot(workspace)) != original:
        raise ValueError('Context comparison mutated source')
    report = {'protocol': 'linked-context-offline-v1', 'source_hash': original,
              'implementation': implementation_metadata(), 'model_calls': 0, 'description': case['public_problem'],
              'config': {'max_chars': 6000, 'top_k': 5, 'dependency_depth': 1, 'assignment_margin': 4},
              'arms': {name: {'chars': sum(len(row['content']) for row in rows), 'evidence': rows}
                       for name, rows in [('base', base), ('linked', linked)]},
              'scope': 'development evidence comparison, not repair success or formal recall'}
    (output / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output / 'comparison.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
