"""Offline diagnostics for the frozen definition-localization pilot; no model calls."""
import argparse
import json
from pathlib import Path

from evals.staged_repair import select_evidence


def analyze(root):
    experiment = json.loads((root / 'experiment.json').read_text(encoding='utf-8'))
    rows = []
    for run in experiment['runs']:
        folder = root / run['policy']
        checkpoint_path = folder / 'localization-checkpoint.json'
        trace = [json.loads(line) for line in (folder / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]
        definitions = [r for r in trace if r['event'] == 'definition_read']
        row = {'policy': run['policy'], 'status': run['status'], 'actual_tokens': run['metrics']['budget_accounted_tokens'],
               'definition_calls': len(definitions),
               'complete_definition_responses': sum(r['response'].get('complete_symbol', False) for r in definitions),
               'definition_responses': [r['response'] for r in definitions],
               'preflight': [r for r in trace if r['event'] == 'request_preflight'],
               'budget_stops': [r for r in trace if r['event'] == 'budget_blocked'],
               'source_unchanged': run['source_unchanged']}
        if checkpoint_path.exists():
            checkpoint = json.loads(checkpoint_path.read_text(encoding='utf-8'))
            reads = checkpoint['pool']['reads']
            keys = [(r['path'], r['content_hash'], n) for r in reads for n in range(r['start_line'], r['end_line'] + 1)]
            evidence = select_evidence(reads, checkpoint['pool']['seeds'], checkpoint['config']['search_max_chars'])
            row.update(read_fragments=len(reads), acquired_lines=len(keys), unique_lines=len(set(keys)),
                       duplicate_lines=len(keys)-len(set(keys)), selected_fragments=len(evidence),
                       candidate_pool_hash=checkpoint['localization_result']['candidate_pool_hash'])
        rows.append(row)
    return {'purpose': 'post-hoc localization diagnostics; no repair-success claim', 'runs': rows,
            'actual_tokens': experiment.get('actual_tokens'), 'repair_runs': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    result = analyze(args.run)
    path = args.run / 'analysis.json'
    if path.exists():
        raise ValueError('Analysis already exists')
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(path)


if __name__ == '__main__':
    main()
