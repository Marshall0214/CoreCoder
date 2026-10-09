"""Strict completion audit for the 50-task paired reasoning trial."""
import argparse
import json
from collections import Counter
from pathlib import Path

from docs.experiments import repair_trial_report_v1 as reports

POLICIES = ('deepseek-off', 'deepseek-high')


def compare(manifest, history, trial):
    protocol = trial['protocol']
    expected = {c['task_id'] for c in manifest['cases']}
    if (protocol['scope'] != 'full' or len(expected) != 50 or len(trial['runs']) != 100
            or set(protocol['policies']) != set(POLICIES)
            or set(protocol['tasks']) != expected
            or any(r['policy'] not in POLICIES for r in trial['runs'])):
        raise ValueError('Require exactly two complete fixed 50-task arms')
    configs = {p: dict(protocol['per_policy_config'][p]) for p in POLICIES}
    if configs[POLICIES[0]].pop('reasoning_effort') != 'none' or configs[POLICIES[1]].pop('reasoning_effort') != 'high':
        raise ValueError('Unexpected thinking configuration')
    if configs[POLICIES[0]] != configs[POLICIES[1]]:
        raise ValueError('Paired budget or model configuration differs')
    arms = {p: reports.audited_rows(trial, p, expected) for p in POLICIES}
    same_prompts = 0
    totals = {}
    for p, rows in arms.items():
        failures = Counter()
        for row in rows.values():
            worker, process = row['worker'], row['process']
            metrics = worker.get('metrics')
            calls = worker.get('provider_calls')
            if (metrics is None or metrics.get('missing_usage_calls', 0) or not calls
                    or len(calls) != metrics['llm_calls']
                    or any(not c.get('response_received') or c.get('total_tokens') is None for c in calls)):
                raise ValueError('Missing or unknown provider usage')
            if sum(c['total_tokens'] for c in calls) != metrics['budget_accounted_tokens']:
                raise ValueError('Returned usage differs from charged trial tokens')
            if row['accepted'] and (process['returncode'] != 0 or process['timed_out']
                                    or not worker.get('published')
                                    or metrics['budget_accounted_tokens'] > configs[p]['token_budget']):
                raise ValueError('Accepted candidate contradicts process, publication or budget')
            if not row['accepted']:
                failures['independent_verification_failure' if worker['status'] == 'completed' else worker['status']] += 1
        totals[p] = {'tasks': 50, 'passed': sum(r['accepted'] for r in rows.values()),
                     'calls': sum(r['worker']['metrics']['llm_calls'] for r in rows.values()),
                     'tokens': sum(r['worker']['metrics']['budget_accounted_tokens'] for r in rows.values()),
                     'seconds': round(sum(r['process']['seconds'] for r in rows.values()), 4),
                     'failure_categories': dict(failures)}
    off, high = (arms[p] for p in POLICIES)
    for task in sorted(expected):
        if off[task]['worker']['provider_calls'][0]['prompt_hash'] != high[task]['worker']['provider_calls'][0]['prompt_hash']:
            raise ValueError('First model input differs between arms')
        same_prompts += 1
    return {'scope': 'full', 'complete': True, 'tasks_per_arm': 50, 'first_prompts_equal': same_prompts,
            'summary': totals,
            'gained': sorted(t for t in expected if high[t]['accepted'] and not off[t]['accepted']),
            'lost': sorted(t for t in expected if off[t]['accepted'] and not high[t]['accepted']),
            'token_increase_percent': round((totals[POLICIES[1]]['tokens'] / totals[POLICIES[0]]['tokens'] - 1) * 100, 2),
            'historical_comparisons': {p: reports.compare(manifest, history, trial, p) for p in POLICIES},
            'full_pool_numeric_target_met': totals[POLICIES[1]]['passed'] >= 38,
            'limits': 'Known fixed tasks; one stochastic trial; equal budget ceilings, different actual compute; cloud weights not frozen'}


def audit(trial_path, output):
    baseline = reports.baseline
    source = baseline.BASE / 'system-comparison-v1-rerun'
    manifest = baseline.load(source / 'manifest.json')
    history = baseline.load(source / 'experiment.json')
    trial = baseline.load(trial_path)
    baseline.intact(manifest)
    for path, expected in trial['protocol']['input_hashes'].items():
        if baseline.previous.admission.history.sha(Path(path)) != expected:
            raise ValueError('Trial protocol input changed')
    if output.exists():
        raise ValueError('Fresh report output required')
    result = compare(manifest, history, trial)
    result.update(trial_path=str(trial_path.resolve()),
                  trial_sha256=baseline.previous.admission.history.sha(trial_path),
                  auditor_sha256=baseline.previous.admission.history.sha(Path(__file__)))
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    audit(args.trial.resolve(), args.output.resolve())
