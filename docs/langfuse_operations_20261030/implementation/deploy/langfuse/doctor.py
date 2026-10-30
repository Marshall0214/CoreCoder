"""Read-only checks for this project's local Langfuse; never calls a model."""
import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx

from repairflow.telemetry import configuration

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ('web', 'worker', 'postgres', 'clickhouse', 'redis', 'minio')
PROBE_ERRORS = (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, AttributeError, httpx.HTTPError)


def command(args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', check=True, timeout=15).stdout


def compose(env_file, *args):
    return ['docker', 'compose', '--project-name', 'corecoder-langfuse', '--env-file', str(env_file), '-f',
            str(ROOT / 'deploy/langfuse/compose.yaml'), *args]


def check(settings, env_file, trace_id=None, *, run=command, transport=None):
    """Keep health and historical readback separate. Never return HTTP bodies or secrets."""
    checks, states = {}, {}
    for service in SERVICES:
        name = 'container:' + service
        try:
            container = run(compose(env_file, 'ps', '--all', '--quiet', service)).strip()
            if not re.fullmatch(r'[0-9a-f]{12,64}', container):
                raise ValueError('Expected exactly one container')
            state = json.loads(run(['docker', 'inspect', '--format', '{{json .State}}', container]))
            state = {key: state.get(key) for key in ('Status', 'Running', 'Paused') } | {
                'health': state.get('Health', {}).get('Status')}
            states[service] = state
            checks[name] = {'passed': state['Running'] is True and state['Paused'] is False
                            and state['health'] in (None, 'healthy'), **state}
        except PROBE_ERRORS as exc:
            checks[name] = {'passed': False, 'error_type': type(exc).__name__}
    with httpx.Client(base_url=settings['base_url'], auth=(settings['public_key'], settings['secret_key']),
                      timeout=3, trust_env=False, transport=transport) as client:
        for name, url in (
            ('web_liveness', '/api/public/health'), ('web_readiness', '/api/public/ready'),
            ('web_database', '/api/public/health?failIfDatabaseUnavailable=true'),
            ('project_auth', '/api/public/projects'),
        ):
            try:
                response = client.get(url)
                passed = response.status_code == 200
                if passed and name == 'project_auth':
                    passed = any(row.get('id') == 'corecoder-issues' for row in response.json().get('data', []))
                checks[name] = {'passed': passed, 'http_status': response.status_code}
            except PROBE_ERRORS as exc:
                checks[name] = {'passed': False, 'error_type': type(exc).__name__}
        readback = {'requested': trace_id is not None, 'proves_fresh_ingestion': False}
        if trace_id is not None:
            if not re.fullmatch(r'[0-9a-f]{32}', trace_id):
                raise ValueError('Expected a 32-character hexadecimal trace id')
            try:
                response = client.get('/api/public/v2/observations', params={
                    'traceId': trace_id, 'limit': 1000, 'fields': 'basic'})
                response.raise_for_status()
                count = len(response.json()['data'])
                readback.update(trace_id=trace_id, observation_count=count, found=count > 0)
            except PROBE_ERRORS as exc:
                readback.update(found=False, error_type=type(exc).__name__)
    worker = states.get('worker', {})
    if worker.get('Running') and not worker.get('Paused'):
        try:
            # This installed image binds its container interface, not loopback.
            script = ("fetch('http://worker:3030/api/health',{signal:AbortSignal.timeout(3000)})"
                      ".then(r=>console.log(r.status)).catch(()=>process.exit(1))")
            status = int(run(compose(env_file, 'exec', '-T', 'worker', 'node', '-e', script)).strip())
            checks['worker_health'] = {'passed': status == 200, 'http_status': status}
        except PROBE_ERRORS as exc:
            checks['worker_health'] = {'passed': False, 'error_type': type(exc).__name__}
    else:
        # Exec into a paused container can block. State alone is already conclusive.
        checks['worker_health'] = {'passed': False, 'reason': 'worker_not_running_or_paused'}
    return {'status': 'healthy' if all(row['passed'] for row in checks.values()) else 'degraded',
            'checked_at': datetime.now(timezone.utc).isoformat(), 'project': 'corecoder-langfuse',
            'checks': checks, 'historical_readback': readback, 'fresh_model_calls': 0,
            'scope': 'Point-in-time diagnostics; fresh ingestion requires a new trace and receipt'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--trace-id')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / '.tmp'):
        parser.error('Use a new output file within project .tmp')
    os.environ['CORECODER_LANGFUSE_ENABLED'] = '1'
    os.environ['CORECODER_LANGFUSE_ENV_FILE'] = str(args.env_file.resolve())
    result = check(configuration(), args.env_file.resolve(), args.trace_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
    return 0 if result['status'] == 'healthy' else 1


if __name__ == '__main__':
    raise SystemExit(main())
