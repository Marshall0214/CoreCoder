"""Verify native Ollama counters against local events, totals and stored Langfuse generations."""
import argparse
import json
import os
import time
from pathlib import Path

import httpx

from deploy.langfuse.verify import payload
from repairflow.telemetry import configuration


def compare(report, events, observations):
    calls = report['provider_calls']
    finished = {event['call_id']: event for event in events if event['event'] in {'llm_finished', 'llm_failed'}}
    generations = [row for row in observations if row.get('type') == 'GENERATION' and row.get('name') == 'model-call']
    if not calls or len(calls) != report['fresh_model_calls'] or len(generations) != len(calls) or len(finished) != len(calls):
        return None
    server = {}
    for row in generations:
        metadata = payload(row.get('metadata')) or {}
        call_id = metadata.get('call_id')
        if call_id in server or not row.get('endTime') or row.get('traceId') != report['observability']['trace_id']:
            return None
        server[call_id] = row
    verified = []
    for index, call in enumerate(calls, 1):
        call_id = f'llm-{index}'
        event, row = finished.get(call_id), server.get(call_id)
        if not event or not row:
            return None
        usage = row.get('usageDetails') or {}
        metadata = payload(row.get('metadata')) or {}
        for native, local, remote in (('prompt_eval_count', 'prompt_tokens', 'input'),
                                      ('eval_count', 'completion_tokens', 'output')):
            expected = (call.get('native_usage') or {}).get(native)
            if call.get(local) != expected or event.get(local) != expected or usage.get(remote) != expected:
                return None
        if (metadata.get('usage_status') != event['usage_status'] or metadata.get('cost_scope') != 'cloud_api_fee'
                or row.get('totalCost') != 0 or event['event'] == 'llm_failed' and row.get('level') != 'ERROR'):
            return None
        verified.append({'call_id': call_id, 'input': event['prompt_tokens'], 'output': event['completion_tokens'],
                         'usage_status': event['usage_status'], 'failed': event['event'] == 'llm_failed'})
    metrics = report['metrics']
    for field, key in (('prompt_tokens', 'input'), ('completion_tokens', 'output')):
        counts = [call[key] for call in verified]
        expected = sum(counts) if all(value is not None for value in counts) else None
        if metrics[field] != expected:
            return None
    return {'status': 'passed', 'scope': 'Local inference usage verification; not a repair-rate experiment',
            'trace_id': report['observability']['trace_id'], 'trace_url': report['observability'].get('trace_url'),
            'server_receipt_verified': True, 'native_local_server_match': True,
            'repair_status': report['status'], 'public_checks_passed': report['public_checks_passed'],
            'model': next(iter(generations)).get('model'), 'thinking': report['thinking'],
            'fresh_model_calls': len(verified), 'prompt_tokens': metrics['prompt_tokens'],
            'completion_tokens': metrics['completion_tokens'], 'cloud_api_cost_usd': metrics['cloud_api_cost_usd'],
            'all_usage_known': all(call['usage_status'] == 'known' for call in verified),
            'local_compute_cost_usd': metrics['local_compute_cost_usd'], 'calls': verified}


def verify(run, settings, timeout):
    run = Path(run)
    report = json.loads((run / 'report.json').read_text(encoding='utf-8'))
    if report['execution_mode'] != 'ollama' or report['thinking'] is not False:
        raise ValueError('Require a local Ollama run with thinking disabled')
    events = [json.loads(line) for line in (run / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    deadline = time.monotonic() + timeout
    with httpx.Client(base_url=settings['base_url'], auth=(settings['public_key'], settings['secret_key']),
                      timeout=5, trust_env=False) as client:
        while time.monotonic() < deadline:
            response = client.get('/api/public/v2/observations', params={
                'traceId': report['observability']['trace_id'], 'limit': 1000, 'fields': 'basic,usage,metadata,model'})
            response.raise_for_status()
            result = compare(report, events, response.json()['data'])
            if result:
                return result
            time.sleep(2)
    raise TimeoutError('Native/local/server usage did not match; no acceptance written')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--env-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--timeout', default=120, type=int)
    args = parser.parse_args()
    output = args.output.resolve()
    root = Path(__file__).resolve().parents[2]
    if output.exists() or not output.is_relative_to(root / '.tmp') or not 1 <= args.timeout <= 600:
        parser.error('Require a new project .tmp output and timeout from 1 to 600')
    os.environ['CORECODER_LANGFUSE_ENABLED'] = '1'
    os.environ['CORECODER_LANGFUSE_ENV_FILE'] = str(args.env_file.resolve())
    result = verify(args.run, configuration(), args.timeout)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
