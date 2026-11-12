"""Read back a scripted Issue demo from local Langfuse; never generates model traffic."""
import argparse
import json
import os
import time
from collections import Counter
from pathlib import Path

import httpx

from repairflow.telemetry import configuration


def payload(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def validate(observations, scores, trace_id, expected_counts=None):
    """Reject partial trees, code-bearing payloads and claims of independent acceptance."""
    roots = [row for row in observations if row.get('name') == 'issue-repair']
    if len(roots) != 1:
        return None
    root = roots[0]
    names = {row.get('name') for row in observations}
    if expected_counts is not None and Counter(row.get('name') for row in observations) != expected_counts:
        return None
    if not {'issue-repair', 'scripted-response', 'apply_patch', 'docker-public-checks'} <= names:
        return None
    # Langfuse v5 may preserve an external physical parent on a logical app root.
    parent = root.get('parentObservationId')
    if ((parent and root.get('isRootObservation') is not True) or parent in {row['id'] for row in observations}
            or any(row.get('traceId') != trace_id or not row.get('endTime') for row in observations)):
        return None
    tool_keys = {'step', 'action', 'status', 'reason', 'path', 'symbol', 'offset', 'edited_files', 'kind',
                 'content_hash', 'next_offset', 'changed_files', 'error_code', 'retryable', 'public_feedback_code'}
    for row in observations:
        if row is root:
            continue
        if row.get('parentObservationId') != root['id']:
            return None
        for field in ('input', 'output'):
            value = payload(row.get(field))
            if row['name'] == 'scripted-response':
                if value is not None:
                    return None
            elif row['name'] == 'docker-public-checks':
                if field == 'input' and value is not None:
                    return None
                if field == 'output' and (not isinstance(value, dict) or any(not isinstance(group, dict)
                        or set(group) - {'tests_run', 'failures', 'errors', 'skipped', 'passed', 'seconds', 'timed_out'}
                        or ('timed_out' in group and type(group['timed_out']) is not bool)
                        for group in value.values())):
                    return None
            elif value is not None and (not isinstance(value, dict) or set(value) - tool_keys):
                return None
    outcome, metadata = payload(root.get('output')), payload(root.get('metadata'))
    if (root.get('input') is not None or not isinstance(outcome, dict) or not isinstance(metadata, dict)
            or set(outcome) - {'status', 'public_checks_passed', 'delivery_status', 'accepted', 'changed_files'}
            or outcome.get('accepted') is not False or outcome.get('public_checks_passed') is not True
            or metadata.get('fresh_model_calls') != 0 or metadata.get('independent_verification_available') is not False):
        return None
    values = {row['name']: row['value'] for row in scores}
    if any(values.get(name) != expected for name, expected in (
            ('public_checks_passed', True), ('independent_verification_available', False), ('fresh_model_calls', 0))):
        return None
    return {'trace_id': trace_id, 'root_id': root['id'], 'observation_count': len(observations),
            'names': sorted(names), 'all_operations_ended': True, 'parent_links_verified': True,
            'local_operation_counts_verified': expected_counts is not None,
            'summary_only_payloads': True, 'scores': values, 'fresh_model_calls': 0, 'independent_acceptance': False}


def verify(demo, settings, timeout=120):
    demo = Path(demo)
    reports = [json.loads((demo / folder / 'report.json').read_text(encoding='utf-8')) for folder in ('cli', 'evidence')]
    trace_ids, expected = [], {}
    for folder, report in zip(('cli', 'evidence'), reports):
        if report['fresh_model_calls'] != 0 or report['accepted'] or not report['public_checks_passed']:
            raise ValueError('Require a successful scripted demo with no independent acceptance')
        trace_ids.append(report['observability']['trace_id'])
        counts = Counter({'issue-repair': 1})
        for line in (demo / folder / 'trace.jsonl').read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            name = {'llm_started': 'scripted-response', 'public_checks_started': 'docker-public-checks',
                    'budget_blocked': 'budget-stop'}.get(event.get('event'))
            if event.get('event') == 'agent_action_started':
                name = event['action']
            if name:
                counts[name] += 1
        expected[trace_ids[-1]] = counts
    if len(set(trace_ids)) != 2:
        raise ValueError('CLI and API must have separate traces')
    deadline, confirmed = time.monotonic() + timeout, {}
    with httpx.Client(base_url=settings['base_url'], auth=(settings['public_key'], settings['secret_key']),
                      timeout=5, trust_env=False) as client:
        client.get('/api/public/health').raise_for_status()
        while time.monotonic() < deadline:
            for trace_id in trace_ids:
                if trace_id in confirmed:
                    continue
                observations = client.get('/api/public/v2/observations', params={
                    'traceId': trace_id, 'limit': 1000, 'fields': 'basic,io,metadata,usage',
                    'expandMetadata': 'metrics,fresh_model_calls,independent_verification_available'})
                observations.raise_for_status()
                scores = client.get('/api/public/v3/scores', params={'traceId': trace_id, 'limit': 100})
                scores.raise_for_status()
                result = validate(observations.json()['data'], scores.json()['data'], trace_id, expected[trace_id])
                if result:
                    confirmed[trace_id] = result
            if len(confirmed) == 2:
                return {'status': 'passed', 'server_receipt_verified': True, 'base_url': settings['base_url'],
                        'scope': 'Scripted engineering acceptance; not model accuracy', 'fresh_model_calls': 0,
                        'traces': list(confirmed.values())}
            time.sleep(2)
    raise TimeoutError('Server did not return complete traces and scores; no receipt claim made')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', required=True, type=Path)
    parser.add_argument('--env-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(root / '.tmp') or not 1 <= args.timeout <= 600:
        parser.error('Use a new output file within project .tmp and a timeout from 1 to 600 seconds')
    os.environ['CORECODER_LANGFUSE_ENABLED'] = '1'
    os.environ['CORECODER_LANGFUSE_ENV_FILE'] = str(args.env_file.resolve())
    result = verify(args.demo, configuration(), args.timeout)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
