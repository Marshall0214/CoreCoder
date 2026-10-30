"""Opt-in local Web/Worker fault drills using a scripted Issue and no model calls."""
import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import httpx

from deploy.langfuse.doctor import ROOT, check, compose
from deploy.langfuse.verify import validate
from repairflow.telemetry import configuration


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def docker(env_file, *args):
    subprocess.run(compose(env_file, *args), cwd=ROOT, check=True, capture_output=True, timeout=90)


@contextmanager
def fault(env_file, service):
    """Restore even if stopping/pausing fails partway; never remove containers or volumes."""
    if service not in {'web', 'worker'}:
        raise ValueError('Only Web and Worker fault drills are supported')
    try:
        docker(env_file, 'stop' if service == 'web' else 'pause', service)
        yield
    finally:
        if service == 'web':
            docker(env_file, 'up', '-d', '--pull', 'never', 'web')
        else:
            docker(env_file, 'unpause', 'worker')


def wait_healthy(settings, env_file, timeout=120):
    deadline = time.monotonic() + timeout
    while True:
        result = check(settings, env_file)
        if result['status'] == 'healthy':
            return result
        if time.monotonic() >= deadline:
            raise TimeoutError('Local Langfuse did not recover; inspect the saved diagnostics')
        time.sleep(2)


def repair(entry, output):
    args = [sys.executable, '-B', '-m', 'repairflow', 'repair-issue',
            '--prepared', str(entry / 'prepared'), '--config', str(entry / 'config/task.json'),
            '--mode', 'scripted', '--responses', str(entry / 'responses.json'),
            '--workflow', 'symbol-recovery-v1', '--observation-policy', 'compact-v1',
            '--max-steps', '4', '--max-edit-attempts', '2', '--output', str(output)]
    subprocess.run(args, cwd=ROOT, check=True, capture_output=True, timeout=120)
    report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    if (report['fresh_model_calls'] != 0 or report['accepted']
            or not report['public_checks_passed'] or not (output / 'patch.diff').stat().st_size):
        raise ValueError('Require public-check success and a nonempty patch, without independent acceptance')
    return {'public_checks_passed': True, 'accepted': False, 'fresh_model_calls': 0,
            'local_trace_present': (output / 'trace.jsonl').is_file(),
            'nonempty_patch': True, 'observability': report['observability']}


def expected_counts(output):
    counts = Counter({'issue-repair': 1})
    for line in (output / 'trace.jsonl').read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        name = {'llm_started': 'scripted-response', 'public_checks_started': 'docker-public-checks',
                'budget_blocked': 'budget-stop'}.get(row.get('event'))
        if row.get('event') == 'agent_action_started':
            name = row['action']
        if name:
            counts[name] += 1
    return counts


def read_trace(client, trace_id, counts):
    response = client.get('/api/public/v2/observations', params={
        'traceId': trace_id, 'limit': 1000, 'fields': 'basic,io,metadata,usage',
        'expandMetadata': 'metrics,fresh_model_calls,independent_verification_available'})
    response.raise_for_status()
    observations = response.json()['data']
    response = client.get('/api/public/v3/scores', params={'traceId': trace_id, 'limit': 100})
    response.raise_for_status()
    scores = response.json()['data']
    return {'observation_count': len(observations), 'score_count': len(scores),
            'receipt': validate(observations, scores, trace_id, counts)}


def run(entry, output, env_file):
    settings = configuration()
    baseline = check(settings, env_file)
    save(output / 'before.json', baseline)
    if baseline['status'] != 'healthy':
        raise ValueError('All six services must be healthy before a fault drill')
    result = {'status': 'incomplete', 'fresh_model_calls': 0, 'scope': 'Synthetic operations drill, not accuracy'}
    try:
        print('Temporarily stopping only Langfuse Web; Issue runs with local evidence.', flush=True)
        with fault(env_file, 'web'):
            save(output / 'web-offline.json', check(settings, env_file))
            result['web_offline_repair'] = repair(entry, output / 'web-offline-repair')
            if result['web_offline_repair']['observability']['status'] != 'unavailable':
                raise ValueError('Expected unavailable telemetry while Web is stopped')
        save(output / 'web-restored.json', wait_healthy(settings, env_file))
        print('Web restored. Pausing only Langfuse Worker to observe ingestion.', flush=True)
        with httpx.Client(base_url=settings['base_url'], auth=(settings['public_key'], settings['secret_key']),
                          timeout=5, trust_env=False) as client:
            with fault(env_file, 'worker'):
                save(output / 'worker-paused.json', check(settings, env_file))
                result['worker_paused_repair'] = repair(entry, output / 'worker-paused-repair')
                trace_id = result['worker_paused_repair']['observability']['trace_id']
                counts = expected_counts(output / 'worker-paused-repair')
                samples, started = [], time.monotonic()
                # Observe this installed version instead of assuming all ingestion needs Worker.
                while True:
                    sample = read_trace(client, trace_id, counts)
                    samples.append({'elapsed_seconds': round(time.monotonic() - started, 2), **sample})
                    if time.monotonic() - started >= 15:
                        break
                    time.sleep(2)
                result['while_worker_paused'] = samples
            print('Worker unpaused; waiting for complete server readback.', flush=True)
            started = time.monotonic()
            while True:
                sample = read_trace(client, trace_id, counts)
                if sample['receipt']:
                    result['after_worker_resumed'] = {
                        'elapsed_seconds': round(time.monotonic() - started, 2), **sample}
                    break
                if time.monotonic() - started > 120:
                    raise TimeoutError('No complete server receipt after Worker resumed')
                time.sleep(2)
        save(output / 'recovered.json', wait_healthy(settings, env_file))
        result['status'] = 'passed'
        return result
    except Exception as exc:
        result['error_type'] = type(exc).__name__
        raise
    finally:
        # Each fault scope restores its own target even when the task/HTTP request fails.
        save(output / 'result.json', result)
        save(output / 'after.json', check(settings, env_file))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output, entry = args.output.resolve(), args.entry.resolve()
    if output.exists() or not output.is_relative_to(ROOT / '.tmp'):
        parser.error('Use a new output directory within project .tmp')
    if not all((entry / name).exists() for name in ('prepared', 'config/task.json', 'responses.json')):
        parser.error('Require a prepared synthetic entry and scripted responses')
    os.environ['CORECODER_LANGFUSE_ENABLED'] = '1'
    os.environ['CORECODER_LANGFUSE_ENV_FILE'] = str(args.env_file.resolve())
    output.mkdir(parents=True)
    try:
        result = run(entry, output, args.env_file.resolve())
    except Exception as exc:  # noqa: BLE001 - redact diagnostics, never expose subprocess output or credentials
        print(json.dumps({'status': 'incomplete', 'error_type': type(exc).__name__, 'output': str(output)}))
        return 1
    print(json.dumps({'status': result['status'], 'fresh_model_calls': 0, 'output': str(output)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
