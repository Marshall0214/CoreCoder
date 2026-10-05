"""Offline 2x3 Python corpus comparison; no model, oracle selection, or repair score."""

import argparse
import json
from pathlib import Path

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
    report = {'protocol': 'symbol-index-offline-v1', 'implementation': implementation_metadata(),
              'source_hash': original, 'description': case['public_problem'], 'model_calls': 0,
              'config': {'max_chars': 6000, 'top_k': 5, 'dependency_depth': 1},
              'scope': 'development relevance diagnostic, not formal recall or model repair', 'arms': {}}
    for mode in ('lines', 'symbols'):
        for query in ('plain', 'aliases', 'identifiers'):
            arm = mode + '-' + query
            evidence = symbol_evidence(workspace, case['public_problem'], allowed,
                                       Events(output / (arm + '.jsonl'), arm), index_mode=mode, query_policy=query)
            if digest(snapshot(workspace)) != original:
                raise ValueError('Source changed during offline comparison')
            report['arms'][arm] = {'evidence_chars': sum(len(row['content']) for row in evidence), 'evidence': evidence}
            (output / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output / 'comparison.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
