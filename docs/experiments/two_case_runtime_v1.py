"""Collect bounded execution facts from the owned candidate and certified public tests."""
import json
import sys
from pathlib import Path

from docs.experiments import frozen_feedback_v1 as guarded
from evals.process import run_process, test_environment
from evals.runner import digest, snapshot

PROBE = Path(__file__).with_name('two_case_probe_v1.py')


def observe(workspace, job, root, outcomes):
    workspace = Path(workspace).resolve()
    harness = Path(job['harness']).resolve()
    before = digest(snapshot(workspace))
    if digest(snapshot(harness)) != job['harness_hash']:
        raise ValueError('Public harness changed')
    root.mkdir(parents=True, exist_ok=False)
    path = root / 'probe-job.json'
    spec = {k: job[k] for k in ('source_root', 'harness', 'package', 'allowed_files')}
    spec['workspace'] = str(workspace)
    path.write_text(json.dumps(spec), encoding='utf-8')
    destination = root / 'result.json'
    process = run_process([sys.executable, '-I', '-B', str(PROBE), str(path), str(destination)], workspace, 15,
                          root / 'stdout.txt', root / 'stderr.txt', test_environment(workspace))
    data = json.loads(destination.read_text(encoding='utf-8')) if destination.exists() else {}
    expected = outcomes['public']
    usable = (process['returncode'] == 0 and not process['timed_out'] and data.get('tests_run', 0) > 0
              and data['tests_run'] == sum(g.get('tests_run', 0) for g in expected.values())
              and data.get('failures') == sum(g.get('failures', 0) for g in expected.values())
              and data.get('errors') == sum(g.get('errors', 0) for g in expected.values())
              and not any(data.get(k, 0) for k in ('skipped', 'expected_failures', 'unexpected_successes', 'omitted_prompt_calls'))
              and not any(r['truncated'] for r in data.get('numeric', [])))
    payload = {'provenance': 'Actual current candidate; certified public tests and their literal constructor inputs only',
               'numeric': data.get('numeric', []), 'prompt_calls': data.get('prompt_calls', []),
               'limits': '12 yielded values per literal range; 4 ranges; 12 prompt calls; primitive arguments only; no fix suggestion'}
    usable = bool(usable and len(json.dumps(payload)) <= 4000 and (payload['numeric'] or payload['prompt_calls']))
    if before != digest(snapshot(workspace)) or digest(snapshot(harness)) != job['harness_hash']:
        raise ValueError('Probe mutated source or public checks')
    guarded.previous.write_json(root / 'observation.json', {'usable': usable, 'process': process, 'payload': payload})
    return payload if usable else None
