"""Validate and summarize the complete compact frozen-pool patch experiment."""

import argparse
import json
from collections import Counter
from pathlib import Path

from staged_compact_live_v1 import ROOT, file_hash


def analyze(path):
    report = json.loads(path.read_text(encoding='utf-8'))
    rows, protocol = report['patch_runs'], report['protocol']
    if not report['complete'] or report['new_localizations'] != 0 or len(rows) != 14:
        raise ValueError('Expected a complete 14-branch experiment')
    if len({(row['task_id'], row['policy']) for row in rows}) != 14:
        raise ValueError('Duplicate experiment branch')
    summary, pairs = {}, []
    for policy in ('read-first', 'compact-read-first-v1'):
        group = [row for row in rows if row['policy'] == policy]
        if {row['task_id'] for row in group} != set(protocol['checkpoints']):
            raise ValueError('Missing task or policy')
        for row in group:
            worker, record = row['worker'], protocol['checkpoints'][row['task_id']]
            metrics, ledger = row['metrics'], worker['budget_accounting']
            if (metrics['llm_calls'] != 1 or metrics['missing_usage_calls'] != 0
                    or worker['candidate_pool_hash'] != record['candidate_pool_hash']
                    or worker['localization_checkpoint_hash'] != record['checkpoint_hash']
                    or ledger['shared_localization_executed_here']
                    or ledger['shared_localization_tokens'] != record['shared_tokens']
                    or ledger['actual_worker_tokens'] != metrics['budget_accounted_tokens']
                    or ledger['patch_tokens'] != metrics['budget_accounted_tokens']
                    or ledger['pipeline_equivalent_tokens'] != record['shared_tokens'] + metrics['budget_accounted_tokens']
                    or row['verification']['scope_violations']):
                raise ValueError('Invalid branch identity, accounting, usage or scope')
            for name in ('ollama_before', 'ollama_after'):
                models = worker[name]['identity']['models']
                if not any(model['name'] == report['config']['model'] and model['digest'] == protocol['model_digest']
                           for model in models):
                    raise ValueError('Model identity changed')
            trace = [json.loads(line) for line in (Path(row['artifacts']) / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            # Event rows use the same runtime event schema as the original worker.
            started = sum(event.get('event') == 'llm_started' for event in trace)
            if started != 1:
                raise ValueError('Expected one actual patch request')
        summary[policy] = {'runs': 7, 'passed': sum(row['accepted'] for row in group),
                           'statuses': dict(Counter(row['status'] for row in group)),
                           'public_passed': sum(row['worker']['public_verification']['passed'] for row in group),
                           'actual_calls': sum(row['metrics']['llm_calls'] for row in group),
                           'prompt_tokens': sum(row['metrics']['known_prompt_tokens'] for row in group),
                           'completion_tokens': sum(row['metrics']['known_completion_tokens'] for row in group),
                           'actual_tokens': sum(row['metrics']['budget_accounted_tokens'] for row in group),
                           'pipeline_equivalent_tokens': sum(row['worker']['budget_accounting']['pipeline_equivalent_tokens'] for row in group),
                           'by_task': {row['task_id']: row['status'] for row in group}}
    historical = json.loads((ROOT / '.tmp/real-defects/staged-shared-repeat-v1/experiment.json').read_text(encoding='utf-8'))
    old = {row['task_id']: row for row in historical['patch_runs']
           if row['repetition'] == 1 and row['staged_evidence_policy'] == 'read-first'}
    for task in protocol['checkpoints']:
        a = next(row for row in rows if row['task_id'] == task and row['policy'] == 'read-first')
        b = next(row for row in rows if row['task_id'] == task and row['policy'] == 'compact-read-first-v1')
        if any(a[key] != b[key] for key in ('fixture_hash', 'visible_checks_hash', 'admission_checks_hash')):
            raise ValueError('Paired fixture or grading changed')
        if a['worker']['patch_non_evidence_hash'] != b['worker']['patch_non_evidence_hash']:
            raise ValueError('Paired non-evidence instructions changed')
        if a['worker']['patch_prompt_hash'] != old[task]['worker']['patch_prompt_hash']:
            raise ValueError('Adapter baseline prompt differs from historical baseline')
        if file_hash(ROOT / protocol['checkpoints'][task]['path']) != protocol['checkpoints'][task]['sha256']:
            raise ValueError('Checkpoint file changed')
        pairs.append({'task_id': task, 'same_pool_and_non_evidence': True, 'baseline_prompt_matches_history': True,
                      'baseline_message_json_chars': a['worker']['message_json_chars'],
                      'compact_message_json_chars': b['worker']['message_json_chars']})
    return {'complete': True, 'experiment_sha256': file_hash(path), 'new_localizations': 0,
            'actual_calls': 14, 'actual_tokens': sum(group['actual_tokens'] for group in summary.values()),
            'historical_shared_tokens': sum(row['shared_tokens'] for row in protocol['checkpoints'].values()),
            'summary': summary, 'pairs': pairs, 'benchmark_eligible': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment', type=Path)
    args = parser.parse_args()
    output = args.experiment.parent / 'analysis.json'
    if output.exists():
        raise ValueError('Preserve existing analysis; use a new output experiment')
    result = analyze(args.experiment)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
