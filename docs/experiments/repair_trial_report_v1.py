"""Audit a complete fixed-policy trial against the frozen full-workflow baseline."""
import argparse
import json
from collections import Counter
from pathlib import Path

from docs.experiments import system_comparison_v1 as baseline


def audited_rows(report, policy, expected):
    if not report['complete']:
        raise ValueError('Trial is still running')
    rows = [r for r in report['runs'] if r['policy'] == policy]
    ids = [r['task_id'] for r in rows]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError('Missing, extra or duplicate task results')
    for row in rows:
        passed = (row['worker']['status'] == 'completed' and row['verification']['passed']
                  and all(g['passed'] for key in ('public', 'frozen') for g in row[key].values())
                  and all(row[key] for key in ('public', 'frozen')))
        if type(row['accepted']) is not bool or row['accepted'] != bool(passed):
            raise ValueError('Accepted result contradicts recorded verification')
    return {r['task_id']: r for r in rows}


def compare(manifest, history, trial, policy):
    scope = trial['protocol']['scope']
    if scope not in ('development', 'full'):
        raise ValueError('Pilot cannot be reported as expanded evaluation')
    cases = [c for c in manifest['cases'] if scope == 'full' or c['split'] == 'development']
    expected = {c['task_id'] for c in cases}
    if len(expected) != (50 if scope == 'full' else 30):
        raise ValueError('Unexpected task pool size')
    current = audited_rows(trial, policy, expected)
    # Historical full report has all 50 tasks; filter only for the development comparison.
    old = dict(history, runs=[r for r in history['runs'] if r['task_id'] in expected])
    previous = audited_rows(old, 'full', expected)
    gained = sorted(t for t in expected if current[t]['accepted'] and not previous[t]['accepted'])
    lost = sorted(t for t in expected if previous[t]['accepted'] and not current[t]['accepted'])
    passed = sum(r['accepted'] for r in current.values())
    missing = sum((r['worker'].get('metrics') or {}).get('missing_usage_calls', 0)
                  for r in current.values())
    unavailable = sum(r['worker'].get('metrics') is None for r in current.values())
    grouped = {}
    for field in ('repo', 'defect_type'):
        if not all(field in c for c in cases):
            continue  # Frozen execution manifests do not necessarily contain taxonomy metadata.
        grouped[field] = {}
        for value in sorted({c[field] for c in cases}):
            tasks = [c['task_id'] for c in cases if c[field] == value]
            grouped[field][value] = {'tasks': len(tasks), 'baseline_passed': sum(previous[t]['accepted'] for t in tasks),
                                    'candidate_passed': sum(current[t]['accepted'] for t in tasks)}
    return {'scope': scope, 'tasks': len(expected), 'baseline_passed': sum(r['accepted'] for r in previous.values()),
            'candidate_passed': passed, 'gained': gained, 'lost': lost,
            'statuses': dict(Counter(r['worker']['status'] for r in current.values())),
            'candidate_calls': sum((r['worker'].get('metrics') or {}).get('llm_calls', 0) for r in current.values()),
            'candidate_tokens': sum((r['worker'].get('metrics') or {}).get('budget_accounted_tokens', 0)
                                    for r in current.values()),
            'missing_usage_calls': missing, 'unavailable_metrics': unavailable, 'grouped': grouped,
            'full_pool_numeric_target_met': scope == 'full' and passed >= 38,
            'limits': 'Known fixed task pool, one stochastic trial; sampled generation/output/interface changes; no blind/generalization claim'}


def audit(trial_path, output, policy='off'):
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
    result = compare(manifest, history, trial, policy)
    result['trial_sha256'] = baseline.previous.admission.history.sha(trial_path)
    result['trial_path'] = str(trial_path.resolve())
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--policy', default='off')
    args = parser.parse_args()
    audit(args.trial.resolve(), args.output.resolve(), args.policy)
