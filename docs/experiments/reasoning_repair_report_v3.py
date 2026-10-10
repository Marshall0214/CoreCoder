"""Summarize a complete local expanded-budget pilot without promoting its score."""
import argparse
import json
from pathlib import Path

from docs.experiments.reasoning_repair_compare_v3 import POLICIES, TASKS, summary


def audit(report):
    rows = report['runs']
    expected = {(task, policy) for task in TASKS for policy in POLICIES}
    actual = [(r['task_id'], r['policy']) for r in rows]
    if not report['complete'] or len(actual) != len(expected) or set(actual) != expected:
        raise ValueError('Require all twelve unique pilot runs')
    paired = {task: {r['policy']: r for r in rows if r['task_id'] == task} for task in TASKS}
    for task, arms in paired.items():
        calls = [arms[p]['worker'].get('provider_calls', []) for p in POLICIES]
        if any(not arm for arm in calls) or calls[0][0]['prompt_hash'] != calls[1][0]['prompt_hash']:
            raise ValueError(f'Missing or mismatched first prompt: {task}')
    return {
        'summary': summary(rows),
        'gained': [t for t, a in paired.items() if a['on']['accepted'] and not a['off']['accepted']],
        'lost': [t for t, a in paired.items() if a['off']['accepted'] and not a['on']['accepted']],
        'first_prompts_match': True,
        'truncated_calls': {p: sum(c.get('finish_reason') == 'length' for r in rows if r['policy'] == p
                                  for c in r['worker'].get('provider_calls', [])) for p in POLICIES},
        'cases': [{'task_id': r['task_id'], 'policy': r['policy'], 'accepted': r['accepted'],
                   'status': r['worker']['status'], 'tokens': (r['worker'].get('metrics') or {}).get('budget_accounted_tokens'),
                   'seconds': r['worker'].get('seconds')} for r in rows],
        'limitation': 'Six selected known development tasks, one trial; not a new full-pool repair rate.',
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(json.loads(args.report.read_text(encoding='utf-8'))), ensure_ascii=False, indent=2))
