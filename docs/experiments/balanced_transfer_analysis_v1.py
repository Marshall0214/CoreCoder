"""Paired development-task matrix; keep the five-task batch separate from prior pilots."""
import argparse
import json
from pathlib import Path

from evals.real_suite import file_hash


def experiment_rows(report):
    if not report['complete']:
        raise ValueError('Cannot analyze an incomplete experiment')
    if len(report['patch_runs']) != report['protocol']['expected_patch_runs']:
        raise ValueError('Wrong paired run count')
    grouped = {}
    for run in report['patch_runs']:
        task, policy = run['task_id'], run['policy']
        if policy not in {'baseline', 'balanced'} or policy in grouped.setdefault(task, {}):
            raise ValueError('Unexpected or duplicate paired policy')
        grouped[task][policy] = run
    if any(set(pair) != {'baseline', 'balanced'} for pair in grouped.values()):
        raise ValueError('Missing paired policy')
    expected_tasks = set(report['protocol'].get('task_order', [report['protocol'].get('task_id')]))
    if set(grouped) != expected_tasks:
        raise ValueError('Unexpected task set')
    output = []
    for task, pair in grouped.items():
        records = report['protocol'].get('tasks', {}).get(task, report['protocol'])['checkpoints']
        if records['baseline']['checkpoint_hash'] != records['balanced']['checkpoint_hash']:
            raise ValueError('Each packing pair requires one shared checkpoint')
        pools = [pair[p].get('worker', {}).get('candidate_pool_hash') for p in ('baseline', 'balanced')]
        prompts = [pair[p].get('worker', {}).get('patch_non_evidence_hash') for p in ('baseline', 'balanced')]
        row = {'task_id': task, 'checkpoint_hash': records['baseline']['checkpoint_hash'],
               'historical_localization_tokens': records['baseline']['localization_tokens'],
               'same_pool': bool(pools[0]) and pools[0] == pools[1],
               'same_non_evidence_prompt': bool(prompts[0]) and prompts[0] == prompts[1], 'policies': {}}
        for policy, run in pair.items():
            metrics = run['metrics']
            verification = run.get('verification') or {}
            row['policies'][policy] = {'accepted': run['accepted'], 'status': run['status'],
                                     'new_tokens': (metrics or {}).get('budget_accounted_tokens', 0),
                                     'model_calls': (metrics or {}).get('llm_calls', 0),
                                     'usage_unknown': metrics is None or (metrics or {}).get('missing_usage_calls', 0) > 0,
                                     'target_passed': (verification.get('target') or {}).get('passed'),
                                     'controls_passed': (verification.get('regression') or {}).get('passed'),
                                     'evidence_chars': run.get('worker', {}).get('evidence_chars'),
                                     'artifacts': run['artifacts']}
        output.append(row)
    return output


def summarize(rows):
    if len({r['task_id'] for r in rows}) != len(rows):
        raise ValueError('Do not count a task twice in one matrix')
    result = {}
    for policy in ('baseline', 'balanced'):
        runs = [r['policies'][policy] for r in rows]
        statuses = {}
        for run in runs:
            statuses[run['status']] = statuses.get(run['status'], 0) + 1
        result[policy] = {'accepted': sum(r['accepted'] for r in runs), 'tasks': len(runs), 'status_counts': statuses,
                          'new_tokens': sum(r['new_tokens'] for r in runs), 'model_calls': sum(r['model_calls'] for r in runs),
                          'usage_unknown_runs': sum(r['usage_unknown'] for r in runs)}
    historical = {}
    for row in rows:
        key = row['checkpoint_hash']
        if key in historical and historical[key] != row['historical_localization_tokens']:
            raise ValueError('Conflicting shared cost')
        historical[key] = row['historical_localization_tokens']
    return {'policies': result, 'new_tokens': sum(r['new_tokens'] for r in result.values()),
            'shared_historical_tokens': sum(historical.values()),
            'historical_plus_new_tokens': sum(historical.values()) + sum(r['new_tokens'] for r in result.values()),
            'paired_gains': [r['task_id'] for r in rows if not r['policies']['baseline']['accepted'] and r['policies']['balanced']['accepted']],
            'paired_losses': [r['task_id'] for r in rows if r['policies']['baseline']['accepted'] and not r['policies']['balanced']['accepted']]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--prior', action='append', type=Path, default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a new output file')
    paths = [args.batch / 'experiment.json', *(p / 'experiment.json' for p in args.prior)]
    primary = experiment_rows(json.loads(paths[0].read_text(encoding='utf-8')))
    prior = [r for path in paths[1:] for r in experiment_rows(json.loads(path.read_text(encoding='utf-8')))]
    all_rows = primary + prior
    result = {'benchmark_eligible': False, 'model_calls_in_analysis': 0, 'primary_five_task_batch': summarize(primary),
              'exploratory_seven_case_matrix': summarize(all_rows), 'cases': all_rows,
              'input_sha256': {str(p): file_hash(p) for p in paths}, 'analysis_sha256': file_hash(Path(__file__)),
              'limitation': 'All cases are development tasks, each arm once. Prior prompt pilot used a newer definition-localization pool; '
                            'the seven-case total is an exploratory assembly, not one uniformly localized suite or held-out success rate.'}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(args.output)


if __name__ == '__main__':
    main()
