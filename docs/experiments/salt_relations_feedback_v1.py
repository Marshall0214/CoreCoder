"""Compare v2 public check feedback with and without a frozen public parameter relation matrix."""

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import anchored_patch_comparison_v1 as preparation
from docs.experiments import repair_public_checks_v1 as public
from docs.experiments import salt_relations_audit_v1 as relations
from docs.experiments import salt_relations_worker_v1 as feedback_worker
from docs.experiments import second_repo_repair_v1 as second
from docs.experiments import symbol_directed_retrieval_v1 as directed
from docs.experiments import validation_repeat_v2 as first
from evals.process import run_process

repair = first.repair
ROOT = first.ROOT
POLICIES = feedback_worker.POLICIES
AUDIT = ROOT / '.tmp/real-defects/salt-relations-audit-v1-final/audit.json'


prepare = preparation.prepare

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
    result['pairs'] = {name: 0 for name in ('both_passed', 'baseline_only', 'feedback_only', 'both_failed', 'incomplete')}
    for pair in pairs.values():
        if len(pair) != 2:
            name = 'incomplete'
        else:
            left, right = pair[POLICIES[0]], pair[POLICIES[1]]
            name = 'both_passed' if left and right else 'baseline_only' if left else 'feedback_only' if right else 'both_failed'
        result['pairs'][name] += 1
    return result


def run(output, repeats=1):
    if type(repeats) is not int or not 1 <= repeats <= 3:
        raise ValueError('Repeat count must be 1 to 3')
    output = output.resolve()
    cases, grading = prepare(output)
    certificate = json.loads(AUDIT.read_text(encoding='utf-8'))
    selected = [(c, g) for c, g in zip(cases, grading) if c['task_id'] == relations.TASK]
    cases, grading = [c for c, _ in selected], [g for _, g in selected]
    if (len(cases) != 1 or not certificate['complete'] or certificate['model_calls'] != 0
            or certificate['source_hash'] != cases[0]['before_hash']
            or certificate['contract'] != relations.contract(cases[0])
            or any(repair.audit.sha(ROOT / name) != sha for name, sha in certificate['adapter_hashes'].items())):
        raise ValueError('Current relation checks lack offline certification')
    matrix = certificate['contract']['rules']
    matrix_hash = hashlib.sha256(json.dumps(matrix, sort_keys=True).encode()).hexdigest()
    repair.check_identity(repair.config())
    output.mkdir(parents=True)
    harnesses = {}
    for case in cases:
        name = case['task_id']
        harness = output / 'public-harnesses' / name
        harness.parent.mkdir(exist_ok=True)
        harness.mkdir(parents=True, exist_ok=False)
        (harness / 'test_admission.py').write_bytes(relations.CHECK.read_bytes())
        harnesses[name] = (harness, repair.digest(repair.snapshot(harness)))
    # Only public cases enter retrieval and worker jobs. No after/scoring labels enter the model.
    observations = directed.observe_all(cases, output)
    if len(observations) != len(cases) or any(o['task_id'] != c['task_id'] for c, o in zip(cases, observations)):
        raise ValueError('Retrieval observations do not match task order')
    frozen_paths = [Path(__file__), Path(public.__file__), Path(feedback_worker.__file__), Path(relations.__file__), relations.CHECK,
                    Path(feedback_worker.context.__file__), AUDIT,
                    *(public.CHECK_ROOT / name for name in public.CHECKS.values()),
                    Path(directed.__file__), Path(preparation.__file__),
                    ROOT / "evals/symbol_index.py", ROOT / "evals/symbol_context.py",
                    ROOT / "corecoder/retrieval/keyword.py", Path(repair.patcher.__file__), Path(repair.__file__),
                    Path(first.__file__), Path(first.validation.__file__), Path(first.retrieval.__file__),
                    Path(second.__file__), Path(second.admission.__file__), first.SPEC, first.validation.MANIFEST, second.MANIFEST]
    hashes = {p.relative_to(ROOT).as_posix(): repair.audit.sha(p) for p in frozen_paths}
    protocol = {'protocol': 'salt-relations-feedback-v1', 'unique_tasks': 1, 'repeats': repeats,
                'expected_runs': 2 * repeats, 'previously_inspected_tasks': True, 'benchmark_eligible': False,
                'prior_runs_included': False, 'config': repair.config().to_dict(), 'engine_hash': repair.audit.ENGINE,
                'repair_model_digest': repair.MODEL_DIGEST, 'max_llm_calls': {policy: 2 for policy in POLICIES}, 'shared_total_token_budget': 15000, 'tools': [],
                'evidence_policy': 'same AST function corpus and complete-function packing; 6000 chars, five seeds, depth zero',
                'intervention': 'same v2 checks, forwarding context, first prompt and two-call cap; only public relation matrix in feedback differs',
                'observations_sha256': repair.audit.sha(output / 'observations.json'), 'adapter_hashes': hashes,
                'public_audit_sha256': repair.audit.sha(AUDIT),
                'public_contract': certificate['contract'], 'relations_hash': matrix_hash,
                'scoring': {c['task_id']: g['case']['checks_hash'] for c, g in zip(cases, grading)},
                'source_hashes': {c['task_id']: c['before_hash'] for c in cases}}
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')

    def check_frozen():
        repair.check_identity(repair.config())
        if (repair.audit.sha(output / 'observations.json') != protocol['observations_sha256']
                or any(repair.audit.sha(ROOT / name) != sha for name, sha in hashes.items())
                or any(repair.digest(repair.snapshot(c['before'])) != c['before_hash'] for c in cases)
                or any(repair.digest(repair.snapshot(g['checks'])) != g['case']['checks_hash'] for g in grading)
                or any(repair.digest(repair.snapshot(path)) != sha for path, sha in harnesses.values())):
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
                evidence = observation['policies']['direct-functions']['evidence']
                repair.validate_evidence(workspace, case['allowed_files'], evidence)
                job_path = root / 'job.json'
                job_path.write_text(json.dumps({'workspace': str(workspace.resolve()), 'description': case['description'],
                                                'allowed_files': case['allowed_files'], 'evidence': evidence,
                                                'task_id': case['task_id'], 'policy': policy, 'test_python': str(item['python']),
                                                'harness': str(harnesses[case['task_id']][0].resolve()),
                                                'harness_hash': harnesses[case['task_id']][1],
                                                'check_code_hash': certificate['contract']['check_sha256'],
                                                'relations': matrix, 'relations_hash': matrix_hash},
                                               ensure_ascii=False), encoding='utf-8')
                module = 'docs.experiments.salt_relations_worker_v1'
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
                                      'evidence_chars': sum(len(r['content']) for r in evidence),
                                      'explicit_symbol_coverage': observation['policies']['direct-functions']['explicit_symbol_coverage'],
                                      'process': process})
                save()
                print(f"{case['task_id']} {policy}: {report['runs'][-1]['status']}", flush=True)
    pairs = {}
    for row in report['runs']:
        pairs.setdefault((row['repeat'], row['task_id']), []).append(row['worker'].get('prompt_hash'))
    if any(len(values) != 2 or None in values or values[0] != values[1] for values in pairs.values()):
        raise ValueError('Initial prompts differ or are unavailable; comparison incomplete')
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
