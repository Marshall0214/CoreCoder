"""New paired calls: exact-old versus anchored ranges, with the same public evidence."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import anchored_patch_v1 as anchored
from docs.experiments import second_repo_repair_v1 as second
from docs.experiments import validation_repeat_v2 as first
from evals.process import run_process

repair = first.repair
ROOT = first.ROOT
POLICIES = ('exact-old', 'anchored-lines')


def prepare(output):
    output = output.resolve()
    if output.exists():
        raise ValueError('Use a fresh output directory')
    click_cases, click_grading, _ = first.prepare(first.validation.MANIFEST,
        ROOT / '.tmp/real-defects/validation-admission-v1-final/admission.json', output)
    other_cases, other_grading, _ = second.prepare(second.MANIFEST,
        ROOT / '.tmp/real-defects/second-repo-admission-v1-final/admission.json', output)
    if repair.audit.sha(first.SPEC) != first.SPEC_SHA:
        raise ValueError('Frozen scoring changed')
    spec = json.loads(first.SPEC.read_text(encoding='utf-8'))
    if spec['v1_manifest_sha256'] != first.validation.MANIFEST_SHA or spec['config'] != repair.config().to_dict():
        raise ValueError('Frozen scoring configuration changed')
    corrected = first.SPEC.parent / spec['updated_checks']
    if repair.digest(repair.snapshot(corrected)) != spec['updated_checks_sha256']:
        raise ValueError('Corrected checks changed')
    for case, grading in zip(click_cases, click_grading):
        if case['task_id'] == spec['corrected_task']:
            grading['checks'] = corrected
            grading['case'] = dict(grading['case'], checks_hash=spec['updated_checks_sha256'])
    cases, grading = click_cases + other_cases, click_grading + other_grading
    if (len(cases) != 6 or len(grading) != 6 or len({c['task_id'] for c in cases}) != 6
            or output.is_relative_to(corrected.resolve())):
        raise ValueError('Expected six distinct tasks and output outside checks')
    return cases, grading


def summarize(rows):
    result = {}
    for policy in POLICIES:
        values = [dict(r, policy=repair.POLICIES[0]) for r in rows if r['policy'] == policy]
        result[policy] = repair.summarize(values)[repair.POLICIES[0]]
    pairs = {}
    for row in rows:
        key = (row['repeat'], row['task_id'])
        if row['policy'] not in POLICIES or row['policy'] in pairs.setdefault(key, {}):
            raise ValueError('Unknown or duplicate comparison branch')
        pairs[key][row['policy']] = row['accepted']
    result['pairs'] = {name: 0 for name in ('both_passed', 'exact_only', 'anchored_only', 'both_failed', 'incomplete')}
    for pair in pairs.values():
        if len(pair) != 2:
            name = 'incomplete'
        else:
            left, right = pair[POLICIES[0]], pair[POLICIES[1]]
            name = 'both_passed' if left and right else 'exact_only' if left else 'anchored_only' if right else 'both_failed'
        result['pairs'][name] += 1
    return result


def run(output, repeats=1):
    if type(repeats) is not int or not 1 <= repeats <= 3:
        raise ValueError('Repeat count must be 1 to 3')
    output = output.resolve()
    cases, grading = prepare(output)
    repair.check_identity(repair.config())
    output.mkdir(parents=True)
    # Only public cases enter retrieval and worker jobs. No after/scoring labels enter the model.
    observations = first.observe_all(cases, output)
    if len(observations) != len(cases) or any(o['task_id'] != c['task_id'] for c, o in zip(cases, observations)):
        raise ValueError('Retrieval observations do not match task order')
    frozen_paths = [Path(__file__), Path(anchored.__file__), Path(repair.patcher.__file__), Path(repair.__file__),
                    Path(first.__file__), Path(first.validation.__file__), Path(first.retrieval.__file__),
                    Path(second.__file__), Path(second.admission.__file__), first.SPEC, first.validation.MANIFEST, second.MANIFEST]
    hashes = {p.relative_to(ROOT).as_posix(): repair.audit.sha(p) for p in frozen_paths}
    protocol = {'protocol': 'anchored-patch-comparison-v1', 'unique_tasks': 6, 'repeats': repeats,
                'expected_runs': 12 * repeats, 'previously_inspected_tasks': True, 'benchmark_eligible': False,
                'prior_runs_included': False, 'config': repair.config().to_dict(), 'engine_hash': repair.audit.ENGINE,
                'repair_model_digest': repair.MODEL_DIGEST, 'llm_calls_per_branch': 1, 'tools': [],
                'evidence_policy': 'python-line-chunks; same raw content and 6000-character cap',
                'intervention': 'patch representation, instructions, fragment IDs and line-number annotation; no new source or retries',
                'line_boundary': 'retain source line terminator when a nonempty replacement omits it; empty replacement deletes lines',
                'observations_sha256': repair.audit.sha(output / 'observations.json'), 'adapter_hashes': hashes,
                'scoring': {c['task_id']: g['case']['checks_hash'] for c, g in zip(cases, grading)},
                'source_hashes': {c['task_id']: c['before_hash'] for c in cases}}
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')

    def check_frozen():
        repair.check_identity(repair.config())
        if (repair.audit.sha(output / 'observations.json') != protocol['observations_sha256']
                or any(repair.audit.sha(ROOT / name) != sha for name, sha in hashes.items())
                or any(repair.digest(repair.snapshot(c['before'])) != c['before_hash'] for c in cases)
                or any(repair.digest(repair.snapshot(g['checks'])) != g['case']['checks_hash'] for g in grading)):
            raise ValueError('Frozen inputs, checks or implementation changed')

    check_frozen()
    for case, item in zip(cases, grading):
        if repair.digest(repair.snapshot(item['source_root'] / 'after')) != item['after_hash']:
            raise ValueError('Reference version changed')
        groups = (second.admission.checked_groups if case['task_id'].startswith('itsdangerous-') else repair.checked_groups)
        for label in ('before', 'after'):
            checked = groups(item['source_root'] / label, item['checks'], output / 'preflight' / case['task_id'] / label,
                             item['python'], 15)
            valid = (checked['Target']['assertion_failure'] and not checked['Target']['execution_error']
                     and not checked['Target']['timed_out'] and not checked['Target']['passed']
                     and checked['Controls']['passed']) if label == 'before' else all(g['passed'] for g in checked.values())
            if not valid:
                raise ValueError('Admitted behavior no longer reproduces')
    report = {'protocol': protocol, 'complete': False, 'runs': []}

    def save():
        report['summary'] = summarize(report['runs'])
        temporary = output / 'experiment.tmp'
        temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
        temporary.replace(output / 'experiment.json')

    save()
    for number in range(1, repeats + 1):
        for index, (case, item, observation) in enumerate(zip(cases, grading, observations)):
            order = POLICIES if (index + number) % 2 else POLICIES[::-1]
            for policy in order:
                check_frozen()
                root = output / f'repeat-{number:02d}' / case['task_id'] / policy
                root.mkdir(parents=True)
                workspace = root / 'workspace'
                shutil.copytree(case['before'], workspace)
                before = repair.snapshot(workspace)
                evidence = observation['policies']['python-line-chunks']['evidence']
                repair.validate_evidence(workspace, case['allowed_files'], evidence)
                job_path = root / 'job.json'
                job_path.write_text(json.dumps({'workspace': str(workspace.resolve()), 'description': case['description'],
                                                'allowed_files': case['allowed_files'], 'evidence': evidence},
                                               ensure_ascii=False), encoding='utf-8')
                module = ('docs.experiments.retrieved_function_repair_v1' if policy == 'exact-old'
                          else 'docs.experiments.anchored_patch_v1')
                env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
                process = run_process([sys.executable, '-m', module, '--worker', str(job_path.resolve())], workspace, 600,
                                      root / 'worker.stdout.txt', root / 'worker.stderr.txt', env)
                path = root / 'worker-result.json'
                result = (json.loads(path.read_text(encoding='utf-8')) if path.exists() and process['returncode'] == 0
                          and not process['timed_out'] else
                          {'status': 'timeout' if process['timed_out'] else 'agent_error', 'metrics': None})
                verifier = second.verify if case['task_id'].startswith('itsdangerous-') else repair.verify
                verification = verifier(item['case'], item['source_root'], item['checks'], workspace, before,
                                        case['allowed_files'], root, item['python'], 15)
                accepted = result['status'] == 'completed' and verification['passed']
                report['runs'].append({'repeat': number, 'task_id': case['task_id'], 'policy': policy, 'worker': result,
                                      'verification': verification, 'accepted': accepted,
                                      'status': 'passed' if accepted else ('failed_verification'
                                                 if result['status'] == 'completed' else result['status']),
                                      'evidence_chars': sum(len(r['content']) for r in evidence), 'process': process})
                save()
                print(f"{case['task_id']} {policy}: {report['runs'][-1]['status']}", flush=True)
    check_frozen()
    if any(repair.digest(repair.snapshot(g['source_root'] / 'after')) != g['after_hash'] for g in grading):
        raise ValueError('Reference changed during comparison')
    report['complete'] = len(report['runs']) == protocol['expected_runs']
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeat', type=int, default=1)
    args = parser.parse_args()
    run(args.output, args.repeat)
