"""Fresh paired development experiment, with a predeclared heldout gate."""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import class_scoped_retrieval_v1 as candidate
from docs.experiments import expanded_baseline_v2 as baseline
from docs.experiments import symbol_directed_retrieval_v1 as symbols
from evals.process import run_process
from evals.runner import digest, snapshot

ROOT = baseline.ROOT
POLICIES = ('baseline', 'class-scoped')


def make_job(case, workspace, evidence):
    return {'workspace': str(workspace), 'description': case['description'],
            'allowed_files': case['allowed_files'], 'evidence': evidence}


def compare(rows):
    return {policy: baseline.summarize([r for r in rows if r['policy'] == policy]) for policy in POLICIES}


def gate(rows):
    development = [r for r in rows if r['split'] == 'development']
    expected = [{r['task_id'] for r in development if r['policy'] == p} for p in POLICIES]
    if len(development) != 60 or expected[0] != expected[1] or len(expected[0]) != 30:
        return {'eligible': False, 'reason': 'require all 30 unique development pairs'}
    summary = compare(development)
    before = summary['baseline']['overall']
    after = summary['class-scoped']['overall']
    gain = after['passed'] - before['passed']
    return {'eligible': gain >= 2 and after['controls_passed'] >= before['controls_passed'],
            'gain': gain, 'baseline_controls_passed': before['controls_passed'],
            'candidate_controls_passed': after['controls_passed'],
            'rule': 'development gain >=2; no increase in control-regression count'}


def run(admitted, output):
    data = json.loads(admitted.read_text(encoding='utf-8'))
    cases = data['cases']
    if (not data['complete'] or len(cases) != 50 or len({c['task_id'] for c in cases}) != 50
            or sum(c['split'] == 'development' for c in cases) != 30
            or sum(c['split'] == 'heldout' for c in cases) != 20):
        raise ValueError('Require complete frozen 30-development/20-heldout admission')
    output = output.resolve()
    if output.exists() or any(output.is_relative_to(Path(c[p]).resolve()) for c in cases for p in ('before', 'after', 'checks')):
        raise ValueError('Fresh output outside frozen inputs required')
    baseline.repair.check_identity(baseline.repair.config())
    output.mkdir(parents=True)
    observed = []
    for case in cases:
        index = baseline.functions.FunctionIndex(Path(case['before']), case['allowed_files'])
        index.refresh()
        plain = baseline.functions.pack(index, index.rank(case['description'] + ' contract contracts'))
        scoped = candidate.retrieve(index, case['description'])
        for packed in (plain, scoped):
            baseline.repair.validate_evidence(Path(case['before']), case['allowed_files'], packed['evidence'])
            assert len(packed['evidence']) <= 5 and packed['metadata']['evidence_chars'] <= 6000
        observed.append({'task_id': case['task_id'], 'policies': dict(zip(POLICIES, [plain, scoped]))})
    observations_path = output / 'observations.json'
    observations_path.write_text(json.dumps(observed, indent=2), encoding='utf-8')
    paths = [admitted, observations_path, Path(__file__), Path(candidate.__file__), Path(symbols.__file__),
             Path(baseline.__file__), Path(baseline.functions.__file__), Path(baseline.envelope.__file__),
             Path(baseline.admission.__file__), Path(baseline.admission.previous.__file__)]
    frozen_hashes = {str(p.resolve()): baseline.admission.history.sha(p) for p in paths}
    report = {'complete': False, 'runs': [], 'protocol': {
        'name': 'class-scoped-comparison-v1', 'config': baseline.repair.config().to_dict(),
        'model_digest': baseline.repair.MODEL_DIGEST, 'engine_hash': baseline.repair.audit.ENGINE,
        'max_model_calls_per_branch': 1, 'max_evidence_chars': 6000, 'max_functions': 5,
        'same_worker': 'docs.experiments.expanded_baseline_v2.worker', 'tools': [],
        'only_changed_factor': 'qualified-symbol/class-scoped retrieval and ordering',
        'paired_order': 'alternate baseline/candidate then candidate/baseline by task index',
        'development_gate': '>=2 additional accepted tasks and no increase in Controls failures',
        'heldout_policy': 'all 20 fresh pairs only if development gate passes; no subsequent strategy edits',
        'private_checks_and_reference_used_as_model_input': False,
        'inputs_and_adapters_sha256': frozen_hashes,
        'limits': 'One run per branch; inspected public tasks; related functions cross splits; no generalization guarantee'}}

    def frozen():
        baseline.repair.check_identity(baseline.repair.config())
        if any(baseline.admission.history.sha(Path(p)) != value for p, value in frozen_hashes.items()):
            raise ValueError('Frozen experiment adapter changed')
        for case in cases:
            for source, key in [('before', 'before_hash'), ('after', 'after_hash'), ('checks', 'checks_hash')]:
                if digest(snapshot(Path(case[source]))) != case[key]:
                    raise ValueError('Frozen source/checks changed')

    def save():
        report['summary'] = compare(report['runs'])
        (output / 'experiment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    frozen()
    save()
    for split in ('development', 'heldout'):
        if split == 'heldout':
            report['development_gate'] = gate(report['runs'])
            save()
            if not report['development_gate']['eligible']:
                report['heldout_status'] = 'not_run_development_gate_failed'
                break
        for offset, (case, observation) in enumerate(zip(cases, observed)):
            if case['split'] != split:
                continue
            for policy in POLICIES if offset % 2 == 0 else reversed(POLICIES):
                frozen()
                root = output / split / case['task_id'] / policy
                root.mkdir(parents=True)
                workspace = root / 'workspace'
                shutil.copytree(case['before'], workspace)
                job_path = root / 'job.json'
                job_path.write_text(json.dumps(make_job(case, workspace, observation['policies'][policy]['evidence']),
                                               ensure_ascii=False), encoding='utf-8')
                process = run_process([sys.executable, '-B', '-m', 'docs.experiments.expanded_baseline_v2',
                                       '--worker', str(job_path)], workspace, 600,
                                      root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                                      dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8'))
                path = root / 'worker-result.json'
                result = (json.loads(path.read_text(encoding='utf-8'))
                          if path.exists() and process['returncode'] == 0 and not process['timed_out']
                          else {'status': 'timeout' if process['timed_out'] else 'agent_error', 'metrics': None})
                verification = baseline.verify(case, workspace, root)
                accepted = result['status'] == 'completed' and verification['passed']
                report['runs'].append({'task_id': case['task_id'], 'repo': case['repo'], 'split': split,
                                       'policy': policy, 'worker': result, 'verification': verification,
                                       'accepted': accepted, 'status': 'passed' if accepted else
                                       'failed_verification' if result['status'] == 'completed' else result['status'],
                                       'process': process, 'evidence_metadata': observation['policies'][policy]['metadata']})
                save()
                print(f"{split} {case['task_id']} {policy}: {report['runs'][-1]['status']}", flush=True)
        if split == 'heldout':
            report['heldout_status'] = 'all_20_pairs_completed'
    frozen()
    report['complete'] = len(report['runs']) == (100 if report['development_gate']['eligible'] else 60)
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.admission.resolve(), args.output.resolve())
