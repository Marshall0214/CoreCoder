"""Freeze healthy original outputs before inference; never recompute candidate expectations."""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import public_feedback_heldout_v1 as previous
from evals.process import run_process, test_environment
from evals.runner import digest, snapshot

policy = previous.policy
TASK = 'more-gray-partial-repeat'
SPECS = [{'pools': [[2, 3], [8, 9]], 'repeat': 2},
         {'pools': [[4, 5]], 'repeat': 2},
         {'pools': [[2, 3, 4], [8, 9]], 'repeat': 1}]
HARVEST = '''
import importlib, json, pathlib, sys
source, specs, destination = sys.argv[1:]
source = pathlib.Path(source).resolve()
sys.path.insert(0, str(source))
m = importlib.import_module('more_itertools')
assert pathlib.Path(m.__file__).resolve().is_relative_to(source)
rows = []
for name in ('gray_product', 'partial_product'):
    for spec in json.loads(specs):
        result = list(getattr(m, name)(*spec['pools'], repeat=spec['repeat']))
        rows.append(dict(api=name, **spec, expected=result))
pathlib.Path(destination).write_text(json.dumps(rows), encoding='utf-8')
'''


def render(rows):
    """Serialize immutable tuples as literals, with no callable expected-result oracle."""
    constants = [dict(row, expected=[tuple(v) for v in row['expected']]) for row in rows]
    return ('"""Expected outputs frozen from healthy original reusable-input behavior."""\n'
            'import unittest\nfrom more_itertools import gray_product, partial_product\n'
            'CASES = ' + repr(constants) + '\n'
            'APIS = {"gray_product": gray_product, "partial_product": partial_product}\n\n'
            'class Reproduce(unittest.TestCase):\n'
            '    def test_one_shot_matches_frozen_expected(self):\n'
            '        for case in CASES:\n'
            '            with self.subTest(api=case["api"], pools=case["pools"], repeat=case["repeat"]):\n'
            '                actual = list(APIS[case["api"]](*(iter(p) for p in case["pools"]), repeat=case["repeat"]))\n'
            '                self.assertEqual(actual, case["expected"])\n\n'
            'class Preserve(unittest.TestCase):\n'
            '    def test_reusable_matches_frozen_expected(self):\n'
            '        for case in CASES:\n'
            '            with self.subTest(api=case["api"], pools=case["pools"], repeat=case["repeat"]):\n'
            '                actual = list(APIS[case["api"]](*case["pools"], repeat=case["repeat"]))\n'
            '                self.assertEqual(actual, case["expected"])\n')


def prepare(admitted, heldout, output):
    old = previous.load(heldout)
    if not old['complete']:
        raise ValueError('Require completed historical run')
    case = next(c for c in previous.cases_from(admitted) if c['task_id'] == TASK)
    historical = heldout.resolve().parent / TASK / 'workspace'
    previous.fresh_output(output, [case], [historical])
    original = Path(case['before'])
    source_hash = digest(snapshot(original))
    oracle = output / 'frozen-expected.json'
    process = run_process([str(policy.admission.PYTHON), '-I', '-B', '-c', HARVEST,
                           str((original / case['source_root']).resolve()), json.dumps(SPECS), str(oracle.resolve())],
                          original, 15, output / 'harvest.stdout.txt', output / 'harvest.stderr.txt', test_environment(original))
    if process['returncode'] or process['timed_out'] or digest(snapshot(original)) != source_hash:
        raise ValueError('Healthy original output harvesting failed/mutated source')
    rows = previous.load(oracle)
    if len(rows) != 6:
        raise ValueError('Incomplete fixed expectation set')
    harness = output / 'checks'
    harness.mkdir()
    (harness / 'test_admission.py').write_text(render(rows), encoding='utf-8')
    outcomes = {label: policy.public_check(path, harness, case['package'], case['source_root'], output / label)
                for label, path in [('before', original), ('after', Path(case['after'])), ('historical-bad', historical)]}
    certified = policy.certified(outcomes) and not outcomes['historical-bad']['Preserve']['passed']
    report = {'complete': bool(certified), 'task_id': TASK, 'model_calls': 0, 'split': 'known-case diagnostic, not heldout',
              'oracle_provenance': 'original source + reusable input specs, frozen before new model calls; no reference oracle',
              'harness': str(harness.resolve()), 'harness_hash': digest(snapshot(harness)), 'outcomes': outcomes,
              'admission_hash': policy.admission.history.sha(admitted),
              'historical_hash': policy.admission.history.sha(heldout),
              'oracle_hash': policy.admission.history.sha(oracle), 'oracle_path': str(oracle.resolve()),
              'adapter_hash': policy.admission.history.sha(Path(__file__)), 'case': case}
    policy.write_json(output / 'certificate.json', report)
    print('Fixed expectations certified; historical shared-iterator patch rejected:', certified, flush=True)


def run(certificate, output):
    cert = previous.load(certificate)
    if not cert['complete'] or cert['adapter_hash'] != policy.admission.history.sha(Path(__file__)):
        raise ValueError('Require certified unchanged fixed checks')
    case = cert['case']
    harness = Path(cert['harness'])
    previous.fresh_output(output, [case], [harness])
    inputs = {str(p.resolve()): policy.admission.history.sha(p) for p in
              (certificate, Path(__file__), Path(policy.__file__), Path(cert['oracle_path']))}
    index = policy.baseline.functions.FunctionIndex(Path(case['before']), case['allowed_files'])
    index.refresh()
    observed = policy.retrieval.retrieve(index, case['description'])
    policy.write_json(output / 'observations.json', observed)
    inputs[str(output / 'observations.json')] = policy.admission.history.sha(output / 'observations.json')

    def frozen():
        policy.repair.check_identity(policy.repair.config())
        if any(policy.admission.history.sha(Path(p)) != h for p, h in inputs.items()):
            raise ValueError('Frozen inputs changed')
        if digest(snapshot(harness)) != cert['harness_hash'] or policy.admission.history.sha(Path(cert['oracle_path'])) != cert['oracle_hash']:
            raise ValueError('Frozen expectations changed')
        for key in ('before', 'after', 'checks'):
            if digest(snapshot(Path(case[key]))) != case[key + '_hash']:
                raise ValueError('Original/reference/private tests changed')

    frozen()
    workspace = output / 'workspace'
    shutil.copytree(case['before'], workspace)
    path = output / 'job.json'
    policy.write_json(path, previous.job_for(case, workspace, observed['evidence'], cert))
    process = run_process([sys.executable, '-B', '-m', 'docs.experiments.public_feedback_v2', '--worker', str(path)],
                          workspace, 600, output / 'worker.stdout.txt', output / 'worker.stderr.txt',
                          dict(os.environ, PYTHONPATH=str(policy.ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
    result_path = output / 'worker-result.json'
    result = previous.load(result_path) if result_path.exists() and process['returncode'] == 0 and not process['timed_out'] else {
        'status': 'timeout' if process['timed_out'] else 'agent_error', 'metrics': None}
    runs = []
    for label, source in [('initial', output / 'initial-workspace'), ('final', workspace)]:
        stage = output / ('validate-' + label)
        stage.mkdir()
        selected = source if source.exists() else workspace
        private = policy.baseline.verify(case, selected, stage)
        public = policy.public_check(selected, harness, case['package'], case['source_root'], stage / 'public')
        status = result.get('initial', {}).get('status', result['status']) if label == 'initial' else result['status']
        runs.append({'stage': label, 'private': private, 'public': public,
                     'accepted': status == 'completed' and private['passed'] and policy.all_pass(public)})
    frozen()
    report = {'complete': True, 'task_id': TASK, 'split': 'known-case diagnostic, not new generalization evidence',
              'protocol': {'worker': 'unchanged public_feedback_v2', 'config': policy.repair.config().to_dict(),
                           'no_private_grader_input': True, 'max_model_calls': 2, 'shared_token_budget': 15000,
                           'frozen_inputs': inputs, 'harness_hash': cert['harness_hash'],
                           'oracle_provenance': cert['oracle_provenance']},
              'worker': result, 'process': process, 'runs': runs,
              'historical_bad_patch_rejected': not cert['outcomes']['historical-bad']['Preserve']['passed']}
    policy.write_json(output / 'experiment.json', report)
    print('Initial accepted:', runs[0]['accepted'], 'Final accepted:', runs[1]['accepted'], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', type=Path)
    parser.add_argument('--heldout', type=Path)
    parser.add_argument('--prepare', type=Path)
    parser.add_argument('--certificate', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.admission and args.heldout and args.prepare:
        prepare(args.admission.resolve(), args.heldout.resolve(), args.prepare.resolve())
    elif args.certificate and args.output:
        run(args.certificate.resolve(), args.output.resolve())
    else:
        parser.error('Use --admission/--heldout/--prepare or --certificate/--output')
