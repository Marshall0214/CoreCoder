"""Separate observed repair outcomes from task defect types and uncertain causes."""
from collections import Counter

LEGACY_TYPES = {
    'click-usage-empty': 'defaults_and_boundaries',
    'click-echo-empty-bytes': 'type_and_representation',
    'click-style-color-validation': 'parameter_validation',
    'itsdangerous-none-salt': 'defaults_and_boundaries',
    'itsdangerous-future-age': 'numeric_consistency',
    'itsdangerous-malformed-time': 'callback_and_exception',
    'click-help-eagerness': 'state_and_consumption',
    'click-flag-default-map': 'defaults_and_boundaries',
    'click-resource-exception': 'callback_and_exception',
    'click-flag-envvar': 'defaults_and_boundaries',
    'click-prompt-suffix': 'type_and_representation',
    'click-invoke-missing': 'defaults_and_boundaries',
    'click-shared-default': 'state_and_consumption',
    'toolz-interpose-empty': 'defaults_and_boundaries',
    'toolz-accumulate-empty': 'defaults_and_boundaries',
    'toolz-join-unmatched': 'defaults_and_boundaries',
    'toolz-getter-empty': 'defaults_and_boundaries',
    'boltons-backoff-constant': 'numeric_consistency',
    'boltons-split-zero': 'defaults_and_boundaries',
    'boltons-chunked-bytes': 'type_and_representation',
    'boltons-remap-set': 'type_and_representation',
    'more-falsy-exception': 'callback_and_exception',
    'more-batch-count': 'parameter_validation',
    'more-seekable-zero': 'state_and_consumption',
    'more-combination-index': 'numeric_consistency',
    'more-split-empty': 'defaults_and_boundaries',
    'more-value-chain-error': 'callback_and_exception',
    'more-interleave-empty': 'defaults_and_boundaries',
    'more-reverse-empty-range': 'numeric_consistency',
    'more-negative-range-slice': 'numeric_consistency',
}


def classify(run):
    """One exclusive outcome plus factual, non-causal diagnostic labels."""
    worker = run['worker']['status']
    verification = run['verification']
    groups = verification.get('groups', {})
    target = bool(groups.get('Target', {}).get('passed'))
    controls = bool(groups.get('Controls', {}).get('passed'))
    labels = []
    if worker == 'budget_exceeded':
        outcome = 'budget_stop'
    elif worker == 'output_truncated':
        outcome = 'output_truncated'
        labels.append('provider_output_limit_reached')
    elif worker == 'invalid_patch':
        outcome = 'invalid_patch'
        labels.append('patch_protocol_rejected')
    elif worker != 'completed':
        outcome = 'execution_fault'
    elif verification.get('scope_violations'):
        outcome = 'scope_violation'
    elif any(g.get('timed_out') or not g.get('tests_run', 0) for g in groups.values()) or not groups:
        outcome = 'grading_fault'
    elif run.get('accepted') and verification['passed'] and target and controls:
        outcome = 'passed'
    elif not controls:
        outcome = 'control_regression'
        labels.append('controls_failed')
        if not target:
            labels.append('target_also_failed')
    elif not target:
        outcome = 'target_failed'
        labels.append('target_failed_with_controls_preserved')
    else:
        outcome = 'inconsistent_result'
    return {'outcome': outcome, 'diagnostic_labels': labels,
            'root_cause': 'not_established' if outcome != 'passed' else None,
            'worker_error': run['worker'].get('error'),
            'target_passed': target, 'controls_passed': controls}


def report(cases, runs):
    by_id = {c['task_id']: c for c in cases}
    if len(by_id) != len(cases) or set(by_id) != {r['task_id'] for r in runs} or len(runs) != len(cases):
        raise ValueError('Require exactly one result for every unique task')
    rows = [dict(task_id=r['task_id'], split=r['split'],
                 defect_type=by_id[r['task_id']].get('defect_type') or LEGACY_TYPES[r['task_id']],
                 **classify(r)) for r in runs]
    summaries = {}
    for category in sorted({r['defect_type'] for r in rows}):
        selected = [r for r in rows if r['defect_type'] == category]
        summaries[category] = {'tasks': len(selected), 'passed': sum(r['outcome'] == 'passed' for r in selected),
                               'outcomes': dict(Counter(r['outcome'] for r in selected))}
    return {'rows': rows, 'by_defect_type': summaries,
            'outcomes': dict(Counter(r['outcome'] for r in rows)),
            'limits': 'Observed outcomes are not causal diagnoses. No inference that failed tests imply retrieval or reasoning failure.'}
