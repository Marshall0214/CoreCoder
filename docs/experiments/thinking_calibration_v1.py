"""Small synthetic calibration: hold all request parameters fixed except native think."""

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import sys
import urllib.request
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from docs.experiments import thinking_calibration_cases_v1 as fixtures
from docs.experiments import thinking_calibration_worker_v1 as worker
from evals.fixed_evidence import apply_patch_json
from evals.process import run_process, test_environment
from evals.runner import digest, snapshot

ROOT = Path(__file__).resolve().parents[2]
MODEL = 'qwen3.5:27b'
MODEL_DIGEST = '7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e'
BOOT = """import importlib.util, pathlib, sys, unittest
source, checks, mode = map(str, sys.argv[1:])
sys.path.insert(0, source)
import app
assert pathlib.Path(app.__file__).resolve() == pathlib.Path(source, 'app.py').resolve()
if mode == 'tests':
    spec = importlib.util.spec_from_file_location('calibration_checks', checks)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(module.Checks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() and result.testsRun > 0 else 1)
"""


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def api(base, endpoint, body=None):
    request = urllib.request.Request(base + endpoint, json.dumps(body).encode() if body else None,
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def identity(base):
    tags = api(base, '/api/tags')['models']
    model = next(row for row in tags if row['name'] == MODEL)
    if model['digest'] != MODEL_DIGEST:
        raise ValueError('Calibration model digest changed')
    show = api(base, '/api/show', {'model': MODEL})
    if 'thinking' not in show.get('capabilities', []):
        raise ValueError('Expected a thinking-capable model')
    return {'version': api(base, '/api/version')['version'], 'digest': model['digest'],
        'thinking_metadata': show.get('thinking'), 'capabilities': show['capabilities'],
        'template_sha256': hashlib.sha256(show.get('template', '').encode()).hexdigest(), 'details': show.get('details')}


def evidence(workspace):
    data = (workspace / 'app.py').read_bytes()
    return [{'path': 'app.py', 'content': data.decode(), 'content_hash': hashlib.sha256(data).hexdigest()}]


def duplicates(text):
    tree = ast.parse(text)
    rows = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for name, count in Counter(n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))).items():
                rows[(node.name, name)] = count
    return rows


def verify(workspace, checks, output, original):
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'source'
    shutil.copytree(workspace, source)
    before, check_hash = digest(snapshot(source)), sha(checks)
    structure = {'parsed': False, 'added_duplicate_methods': []}
    try:
        current, previous = duplicates((source / 'app.py').read_text(encoding='utf-8')), duplicates(original)
        structure.update(parsed=True, added_duplicate_methods=[{'class': owner, 'method': name, 'count': count}
            for (owner, name), count in current.items() if count > 1 and count > previous.get((owner, name), 0)])
    except SyntaxError as exc:
        structure['error'] = f'{type(exc).__name__}: {exc}'
    results = {}
    for mode in ('import', 'tests'):
        result = run_process([sys.executable, '-I', '-B', '-c', BOOT, str(source.resolve()), str(checks.resolve()), mode],
            source, 10, output / (mode + '.stdout.txt'), output / (mode + '.stderr.txt'), test_environment(source))
        text = (output / (mode + '.stderr.txt')).read_text(encoding='utf-8')
        count = re.search(r'Ran (\d+) tests?', text)
        result.update(tests_run=int(count.group(1)) if count else 0,
                      passed=result['returncode'] == 0 and not result['timed_out'])
        if mode == 'tests':
            result['passed'] = result['passed'] and result['tests_run'] > 0
        results[mode] = result
    if before != digest(snapshot(source)) or check_hash != sha(checks):
        raise ValueError('Verification mutated source or checks')
    return {'structure': structure, 'import': results['import'], 'behavior': results['tests'],
            'passed': structure['parsed'] and not structure['added_duplicate_methods']
                       and results['import']['passed'] and results['tests']['passed']}


def summarize(rows):
    result = {}
    for mode in ('off', 'on'):
        values = [r for r in rows if r['mode'] == mode]
        usage = [r['worker'].get('native', {}) for r in values]
        known = all(u.get('response_received') and isinstance(u.get('prompt_tokens'), int)
                    and isinstance(u.get('completion_tokens'), int) for u in usage)
        result[mode] = {'runs': len(values), 'patch_applied': sum(r['worker'].get('patch_applied', False) for r in values),
            'import_passed': sum(r['verification']['import']['passed'] for r in values),
            'behavior_passed': sum(r['verification']['behavior']['passed'] for r in values),
            'accepted': sum(r['accepted'] for r in values),
            'statuses': dict(Counter(r['worker']['status'] for r in values)),
            'provider_reported_total_tokens': sum(u['prompt_tokens'] + u['completion_tokens'] for u in usage) if known else None,
            'thinking_responses': sum(u.get('thinking_present', False) for u in usage),
            'truncated_responses': sum(u.get('done_reason') == 'length' for u in usage)}
    return result


def run(output, repeats=1, base='http://127.0.0.1:11434', live=False):
    if type(repeats) is not int or not 1 <= repeats <= 3:
        raise ValueError('Repeat count must be 1 to 3')
    url = urlparse(base)
    if url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1') or url.path not in ('', '/'):
        raise ValueError('Use a local Ollama endpoint')
    base, output = base.rstrip('/'), output.resolve()
    if output.exists():
        raise ValueError('Use fresh output')
    output.mkdir(parents=True)
    frozen_paths = [Path(__file__), Path(fixtures.__file__), Path(worker.__file__), ROOT / 'evals/fixed_evidence.py',
                    ROOT / 'evals/runtime.py', ROOT / 'evals/process.py', ROOT / 'evals/schema.py', ROOT / 'corecoder/llm.py']
    hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in frozen_paths}
    report = {'protocol': {'protocol': 'thinking-calibration-v1', 'synthetic': True, 'unique_tasks': 4,
        'repeats': repeats, 'live': live, 'expected_runs': 8 * repeats if live else 0,
        'model': MODEL, 'base_url': base, 'fixed_temperature': 0, 'fixed_top_p': 0.95, 'fixed_seed': 17,
        'context_tokens': 16000, 'max_output_tokens': 2048, 'token_budget': 15000,
        'max_calls_per_task': 1, 'adapter_hashes': hashes,
        'intervention': 'native think boolean only; no feedback, tests or reference edits in model input',
        'usage': 'Native prompt_eval_count plus eval_count; thinking/final token split unavailable'},
        'complete': False, 'admission': [], 'runs': []}
    roots = {}
    for case in fixtures.CASES:
        root = output / 'fixtures' / case['id']
        source, harness, positive = root / 'before', root / 'checks', root / 'positive'
        source.mkdir(parents=True); harness.mkdir()
        (source / 'app.py').write_bytes(case['source'].encode())
        (harness / 'test_case.py').write_bytes(case['checks'].encode())
        shutil.copytree(source, positive)
        patch = json.dumps({'edits': [{'file': 'app.py', 'old': old, 'new': new} for old, new in case['reference']]})
        apply_patch_json(patch, positive, ['app.py'], evidence(positive))
        original = verify(source, harness / 'test_case.py', root / 'original-verification', case['source'])
        correct = verify(positive, harness / 'test_case.py', root / 'positive-verification', case['source'])
        if original['passed'] or not correct['passed']:
            raise ValueError('Synthetic task lacks valid negative and positive examples')
        report['admission'].append({'task_id': case['id'], 'before_hash': digest(snapshot(source)),
            'checks_sha256': sha(harness / 'test_case.py'), 'original': original, 'reference': correct})
        roots[case['id']] = (source, harness / 'test_case.py')

    def save():
        report['summary'] = summarize(report['runs'])
        temporary = output / 'experiment.tmp'
        temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
        temporary.replace(output / 'experiment.json')

    def frozen():
        if any(sha(ROOT / name) != value for name, value in hashes.items()):
            raise ValueError('Calibration implementation changed')
        for record in report['admission']:
            source, check = roots[record['task_id']]
            if digest(snapshot(source)) != record['before_hash'] or sha(check) != record['checks_sha256']:
                raise ValueError('Fixture source or checks changed')
        if live and identity(base) != report['protocol']['model_identity']:
            raise ValueError('Model metadata changed during calibration')

    if live:
        report['protocol']['model_identity'] = identity(base)
    save()
    if not live:
        frozen(); report['complete'] = True; save(); return
    for number in range(1, repeats + 1):
        for index, case in enumerate(fixtures.CASES):
            order = (False, True) if (number + index) % 2 else (True, False)
            for thinking in order:
                frozen()
                mode = 'on' if thinking else 'off'
                root = output / f'repeat-{number:02d}' / case['id'] / mode
                root.mkdir(parents=True)
                workspace = root / 'workspace'
                source, check = roots[case['id']]
                shutil.copytree(source, workspace)
                job = {'workspace': str(workspace), 'description': case['description'], 'allowed_files': ['app.py'],
                       'files': evidence(workspace), 'thinking': thinking, 'model': MODEL, 'base_url': base}
                path = root / 'job.json'
                path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
                process = run_process([sys.executable, '-B', '-m', 'docs.experiments.thinking_calibration_worker_v1',
                    '--worker', str(path)], workspace, 150, root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                    dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
                result_path = root / 'worker-result.json'
                result = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() and not process['timed_out'] else {
                    'status': 'worker_timeout' if process['timed_out'] else 'worker_error', 'patch_applied': False}
                checked = verify(workspace, check, root / 'verification', case['source'])
                accepted = result.get('patch_applied', False) and checked['passed']
                report['runs'].append({'repeat': number, 'task_id': case['id'], 'mode': mode, 'worker': result,
                                       'verification': checked, 'accepted': accepted, 'process': process})
                save()
                print(f"{case['id']} thinking-{mode}: {result['status']}; accepted={accepted}", flush=True)
    pairs = {}
    for row in report['runs']:
        pairs.setdefault((row['repeat'], row['task_id']), []).append(row['worker'].get('prompt_sha256'))
    if any(len(v) != 2 or None in v or v[0] != v[1] for v in pairs.values()):
        raise ValueError('Paired prompts differ or are unavailable')
    frozen()
    report['complete'] = len(report['runs']) == report['protocol']['expected_runs']
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--base-url', default='http://127.0.0.1:11434')
    args = parser.parse_args()
    run(args.output, args.repeat, args.base_url, args.live)
