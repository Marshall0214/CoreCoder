"""Append bounded public predicate observations without changing context or prompts."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

from docs.experiments import frozen_feedback_v1 as guarded
from evals.process import run_process, test_environment
from evals.runner import digest, snapshot

previous = guarded.previous
PROBE = Path(__file__).with_name('predicate_trace_probe_v1.py')


def observe(workspace, job, root, outcomes):
    harness = Path(job['harness'])
    before = digest(snapshot(workspace))
    if digest(snapshot(harness)) != job['harness_hash']:
        raise ValueError('Public harness changed')
    root.mkdir()
    groups = []
    for group in ('Reproduce', 'Preserve'):
        destination = root / (group + '.json')
        process = run_process([sys.executable, '-I', '-B', str(PROBE), str(workspace), job['source_root'],
                               str(harness), job['package'], json.dumps(job['allowed_files']), group, str(destination)],
                              workspace, 15, root / (group + '.stdout.txt'), root / (group + '.stderr.txt'),
                              test_environment(workspace))
        data = json.loads(destination.read_text(encoding='utf-8')) if destination.exists() else {}
        expected = outcomes['public'][group]
        usable = (process['returncode'] == 0 and not process['timed_out'] and data.get('tests_run', 0) > 0
                  and data.get('tests_run') == expected.get('tests_run')
                  and len(data.get('records', [])) == data.get('tests_run')
                  and data.get('successful') == expected['passed']
                  and not any(data.get(k, 0) for k in ('skipped', 'expected_failures', 'unexpected_successes'))
                  and not any(r['truncated'] for r in data.get('records', [])))
        groups.append({'group': group, 'usable': bool(usable), 'process': process, 'data': data})
    if before != digest(snapshot(workspace)) or digest(snapshot(harness)) != job['harness_hash']:
        raise ValueError('Probe mutated source or public checks')
    records = [{'group': g['group'], **r} for g in groups for r in g.get('data', {}).get('records', [])]
    payload = {'source': 'Current candidate running certified readable public tests only',
               'records': records, 'limits': '12 operations/test, 16 predicate calls/operation, 12 values/sequence; '
               'only explicit operation inputs and callback arguments/return/exception type, no other locals; '
               'not-captured objects are not proven padding; observations do not establish root cause'}
    usable = all(g['usable'] for g in groups) and len(json.dumps(payload)) <= 5000
    previous.write_json(root / 'observation.json', {'usable': usable, 'groups': groups, 'payload': payload})
    return payload if usable else None


def run_candidate(llm, job, events):
    original = guarded.feedback

    def feedback(outcomes, workspace, job, root):
        result = original(outcomes, workspace, job, root)
        data = observe(workspace, job, root / 'predicate-probe', outcomes)
        if data is not None:
            result['public_runtime_observations'] = data
        events.emit('predicate_observation', added=data is not None)
        return result

    with patch.object(guarded, 'feedback', feedback):
        result = guarded.run_candidate(llm, job, events)
    result['protocol'] = 'predicate-runtime-v1'
    return result
