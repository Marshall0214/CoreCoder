"""Fresh paired Qwen public-grounded repair hypothesis comparison; public and private checks remain separate."""

import argparse
import importlib.metadata
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from docs.experiments import anchored_patch_comparison_v1 as preparation
from docs.experiments import provider_compare_worker_v1 as provider_worker
from docs.experiments import repair_hypothesis_worker_v2 as worker
from docs.experiments import repair_public_checks_v1 as public
from docs.experiments import runtime_observation_v1 as observer
from docs.experiments import salt_relations_audit_v1 as relations
from docs.experiments import second_repo_repair_v1 as second
from docs.experiments import source_contract_context_v1 as contracts
from docs.experiments import symbol_directed_retrieval_v1 as directed
from docs.experiments import thinking_calibration_v1 as calibration
from evals.process import run_process

repair = public.repair
ROOT = public.ROOT
POLICIES = ('patch-only', 'public-hypotheses')



def audit(output):
    output = output.resolve()
    cases, _ = preparation.prepare(output)
    case = next(c for c in cases if c['task_id'] == relations.TASK)
    history = ROOT / '.tmp/real-defects/edited-context-compare-v1/itsdangerous-none-salt/edited-first'
    source = history / 'public-candidate/source'
    source_hash = repair.digest(repair.snapshot(source))
    code = worker.canonical_check(case['task_id']).read_text(encoding='utf-8')
    observation = json.loads((history / 'public-candidate/observation.json').read_text(encoding='utf-8'))
    diagnostic = worker.planning.diagnose(code, observation)
    evidence = json.loads((history / 'feedback-context.json').read_text(encoding='utf-8'))['evidence']
    hypotheses = [{'tests': [r['test'] for r in diagnostic['required_failures']],
                   'symbols': [f"{r['path']}:{r['symbol']}" for r in evidence],
                   'claim': 'Proposed repair must satisfy the referenced public checks.'}]
    proposal = json.dumps({'hypotheses': hypotheses, 'edits': []})
    _, validated = worker.planning.validate(proposal, evidence, diagnostic)
    negative = dict(hypotheses[0], symbols=['absent.py:missing'])
    rejected = False
    try:
        worker.planning.validate(json.dumps({'hypotheses': [negative], 'edits': []}), evidence, diagnostic)
    except worker.planning.InvalidHypothesis:
        rejected = True
    output.mkdir(parents=True, exist_ok=False)
    harness = output / 'harness'
    harness.mkdir()
    (harness / 'test_admission.py').write_text(code, encoding='utf-8')
    value = repair.digest(repair.snapshot(harness))
    python = ROOT / '.tmp/real-defects/click-stdlib-env/Scripts/python.exe'
    witness = output / 'witness'
    shutil.copytree(case['before'], witness)
    public.apply_witness(case, witness)
    positive, _ = observer.check_public(witness, harness, value, output / 'positive', python, case['task_id'])
    replay, _ = observer.check_public(history / 'workspace', harness, value, output / 'historical-final', python, case['task_id'])
    positive_assessment = worker.planning.assess(validated, code, positive)
    replay_assessment = worker.planning.assess(validated, code, replay)
    ready = (rejected and positive['passed'] and positive_assessment[0]['status'] == 'supported_on_public_checks'
             and replay_assessment[0]['status'] == 'failed_public_checks'
             and repair.digest(repair.snapshot(source)) == source_hash)
    result = {'protocol': 'repair-hypothesis-audit-v2', 'complete': ready, 'model_calls': 0,
              'source_hashes': {c['task_id']: c['before_hash'] for c in cases},
              'implementation_sha256': repair.audit.sha(Path(worker.planning.__file__)),
              'public_check_sha256': repair.audit.sha(worker.canonical_check(case['task_id'])),
              'historical_source_hash': source_hash, 'diagnostic': diagnostic,
              'reference_negative_rejected': rejected, 'positive': positive_assessment, 'historical_final': replay_assessment,
              'scope': 'synthetic hypothesis reference validation and real public-outcome replay; not a model gain'}
    (output / 'audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if not ready:
        raise ValueError('Public hypothesis offline audit failed')
    print(json.dumps({'complete': True, 'model_calls': 0, 'required_methods': len(diagnostic['required_failures'])}))


def summarize(rows):
    result = {}
    for policy in POLICIES:
        values = [dict(row, policy=repair.POLICIES[0]) for row in rows if row['policy'] == policy]
        result[policy] = repair.summarize(values)[repair.POLICIES[0]]
        result[policy]['model_calls'] = sum((r['worker'].get('metrics') or {}).get('llm_calls', 0)
                                           for r in rows if r['policy'] == policy)
        result[policy]['transaction_rejections'] = sum(
            not s['transaction']['accepted'] for r in rows if r['policy'] == policy
            for s in r['worker'].get('stages', []) if 'transaction' in s)
    return result


def run(output, task_ids=None):
    output = output.resolve()
    cases, grades = preparation.prepare(output)
    source_hashes = {c['task_id']: c['before_hash'] for c in cases}
    if task_ids:
        if len(set(task_ids)) != len(task_ids) or set(task_ids) - {c['task_id'] for c in cases}:
            raise ValueError('Unknown or duplicate task selection')
        selected = [(c, g) for c, g in zip(cases, grades) if c['task_id'] in task_ids]
        cases, grades = [c for c, _ in selected], [g for _, g in selected]
    audit_path = ROOT / '.tmp/real-defects/runtime-observation-audit-v1/audit.json'
    audited = json.loads(audit_path.read_text(encoding='utf-8'))
    if (not audited['complete'] or audited['model_calls'] != 0
            or audited['observer_sha256'] != repair.audit.sha(Path(observer.__file__))):
        raise ValueError('Source context lacks current offline audit')
    if audited['source_hashes'] != source_hashes:
        raise ValueError('Offline context source differs')
    retention_audit = ROOT / '.tmp/real-defects/edited-context-audit-v1-final/audit.json'
    retained = json.loads(retention_audit.read_text(encoding='utf-8'))
    if (not retained['complete'] or retained['model_calls'] != 0
            or retained['source_hashes'] != source_hashes
            or retained['implementation_sha256'] != repair.audit.sha(Path(worker.retention.__file__))):
        raise ValueError('Edited context lacks current offline audit')
    planning_audit = ROOT / '.tmp/real-defects/repair-hypothesis-audit-v2/audit.json'
    planned = json.loads(planning_audit.read_text(encoding='utf-8'))
    if (not planned['complete'] or planned['model_calls'] != 0 or planned['source_hashes'] != source_hashes
            or planned['implementation_sha256'] != repair.audit.sha(Path(worker.planning.__file__))
            or planned['public_check_sha256'] != repair.audit.sha(worker.canonical_check(relations.TASK))):
        raise ValueError('Repair hypotheses lack current offline audit')
    # Frozen offline certificates authorize only public development checks.
    certificates = [ROOT / '.tmp/real-defects/repair-public-checks-audit-v1-certified/audit.json',
                    ROOT / '.tmp/real-defects/salt-relations-audit-v1-final/audit.json']
    click, salt = [json.loads(p.read_text(encoding='utf-8')) for p in certificates]
    if (not click['complete'] or click['model_calls'] != 0 or not salt['complete'] or salt['model_calls'] != 0
            or click['implementation_sha256'] != repair.audit.sha(Path(public.__file__))
            or any(repair.audit.sha(ROOT / name) != value for name, value in salt['adapter_hashes'].items())):
        raise ValueError('Public checks lack current offline certification')
    for case in cases:
        if case['task_id'] == relations.TASK:
            if case['before_hash'] != salt['source_hash'] or relations.contract(case) != salt['contract']:
                raise ValueError('Salt public certificate differs from source')
        elif case['task_id'] == public.TARGETS[0]:
            record = next(c for c in click['tasks'] if c['task_id'] == case['task_id'])
            if (record['source_hash'] != case['before_hash'] or click['registry'][case['task_id']]['code_sha256']
                    != repair.audit.sha(worker.canonical_check(case['task_id']))):
                raise ValueError('Click public certificate differs from source')
    repair.check_identity(repair.config())
    ollama_identity = calibration.identity('http://localhost:11434')
    output.mkdir(parents=True, exist_ok=False)
    harnesses = {}
    for case in cases:
        code = worker.canonical_check(case['task_id'])
        if code is not None:
            harness = output / 'public-harnesses' / case['task_id']
            harness.mkdir(parents=True)
            (harness / 'test_admission.py').write_bytes(code.read_bytes())
            harnesses[case['task_id']] = (harness, repair.digest(repair.snapshot(harness)))
    observations = directed.observe_all(cases, output)
    paths = [Path(__file__), Path(worker.planning.__file__), Path(worker.retention.__file__), Path(worker.retention.functions.__file__), Path(provider_worker.__file__), Path(worker.__file__), Path(contracts.__file__), Path(observer.__file__), Path(worker.guard.__file__), Path(worker.context.__file__),
             Path(public.__file__), Path(relations.__file__), Path(directed.__file__), Path(preparation.__file__), Path(calibration.__file__),
             Path(second.__file__), Path(repair.__file__), Path(repair.patcher.__file__),
             ROOT / 'evals/symbol_context.py', ROOT / 'evals/symbol_index.py', ROOT / 'evals/runtime.py',
             ROOT / 'evals/process.py', planning_audit, retention_audit, audit_path, *certificates, *(worker.canonical_check(c['task_id']) for c in cases
                                                      if worker.canonical_check(c['task_id']) is not None)]
    hashes = {p.relative_to(ROOT).as_posix(): repair.audit.sha(p) for p in paths}
    protocol = {'protocol': 'public-repair-hypotheses-v2', 'unique_tasks': len(cases), 'repeats': 1,
                'started_at_utc': datetime.now(timezone.utc).isoformat(), 'ollama_identity': ollama_identity,
                'sdk_version': importlib.metadata.version('openai'),
                'expected_runs': 2 * len(cases), 'previously_inspected_tasks': True, 'benchmark_eligible': False,
                'prior_runs_included': False, 'config': repair.config().to_dict(), 'engine_hash': repair.audit.ENGINE,
                'qwen_model_digest': repair.MODEL_DIGEST, 'provider': provider_worker.PROVIDERS['qwen'], 'planning_policies': POLICIES, 'retention_policy': 'edited-first', 'feedback_policy': 'runtime-feedback', 'context_policy': 'source-contract',
                'sampling': {'temperature': 0, 'top_p': 1, 'seed': None, 'stream': False},
                'thinking_policy': 'explicitly disabled; reject returned reasoning; record absent reasoning token breakdown as unknown',
                'transport': 'OpenAI-compatible SDK, 60-second timeout, zero automatic retries',
                'max_llm_calls_per_branch': 2, 'shared_token_budget': 15000,
                'tools': [], 'adapter_hashes': hashes,
                'evidence_policy': 'same source-contract context on none-salt in both arms; other five original retrieval; combined 6000 chars and five seeds',
                'intervention': 'same edited-function context and runtime-feedback gate; second public-feedback response adds bounded public-test/source hypotheses and reference/coverage validation; no extra request',
                'public_check_versions': {c['task_id']: repair.audit.sha(worker.canonical_check(c['task_id'])) for c in cases
                                          if worker.canonical_check(c['task_id']) is not None},
                'regression_scope': 'four tasks without certified public checks use single initial repair; transaction failures may use one feedback',
                'observations_sha256': repair.audit.sha(output / 'observations.json'),
                'source_hashes': {c['task_id']: c['before_hash'] for c in cases},
                'scoring': {c['task_id']: g['case']['checks_hash'] for c, g in zip(cases, grades)}}
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    def frozen():
        repair.check_identity(repair.config())
        if (calibration.identity('http://localhost:11434') != ollama_identity
                or any(repair.audit.sha(ROOT / name) != value for name, value in hashes.items())
                or repair.audit.sha(output / 'observations.json') != protocol['observations_sha256']
                or any(repair.digest(repair.snapshot(c['before'])) != c['before_hash'] for c in cases)
                or any(repair.digest(repair.snapshot(g['checks'])) != g['case']['checks_hash'] for g in grades)
                or any(repair.digest(repair.snapshot(g['source_root'] / 'after')) != g['after_hash'] for g in grades)
                or any(repair.digest(repair.snapshot(h)) != value for h, value in harnesses.values())):
            raise ValueError('Frozen inputs changed')
    # Private before/after admission recheck is parent-owned, never passed to worker jobs.
    for case, grade in zip(cases, grades):
        groups = second.admission.checked_groups if case['task_id'].startswith('itsdangerous-') else repair.checked_groups
        for label in ('before', 'after'):
            checked = groups(grade['source_root'] / label, grade['checks'], output / 'preflight' / case['task_id'] / label,
                             grade['python'], 15)
            valid = (public.valid_failure(checked['Target']) and checked['Controls']['passed']) if label == 'before' else all(
                value['passed'] for value in checked.values())
            if not valid:
                raise ValueError('Admitted defect or controls no longer reproduce')
    report = {'protocol': protocol, 'complete': False, 'runs': []}
    def save():
        report['summary'] = summarize(report['runs'])
        (output / 'experiment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    for index, (case, grade, observation) in enumerate(zip(cases, grades, observations)):
        for policy in (POLICIES if index % 2 else POLICIES[::-1]):
            frozen()
            root = output / case['task_id'] / policy
            workspace = root / 'workspace'
            shutil.copytree(case['before'], workspace)
            before = repair.snapshot(workspace)
            evidence = observation['policies']['direct-functions']['evidence']
            job = {'workspace': str(workspace.resolve()), 'description': case['description'], 'allowed_files': case['allowed_files'],
                   'evidence': evidence, 'task_id': case['task_id'], 'policy': 'unified-feedback', 'context_policy': 'source-contract', 'feedback_policy': 'runtime-feedback', 'retention_policy': 'edited-first', 'planning_policy': policy, 'test_python': str(grade['python'])}
            package = 'itsdangerous' if case['task_id'].startswith('itsdangerous-') else 'click'
            job['imports'] = [{'module': package, 'root': 'src', 'path': f'src/{package}/__init__.py'}]
            if case['task_id'] in harnesses:
                harness, value = harnesses[case['task_id']]
                job.update(harness=str(harness.resolve()), harness_hash=value,
                           check_code_hash=protocol['public_check_versions'][case['task_id']])
            path = root / 'job.json'
            path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
            process = run_process([sys.executable, '-B', '-m', 'docs.experiments.repair_hypothesis_worker_v2', '--worker', str(path.resolve())],
                                  workspace, 600, root / 'worker.stdout.txt', root / 'worker.stderr.txt',
                                  dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1'))
            result_path = root / 'worker-result.json'
            result = (json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() and not process['timed_out']
                      and process['returncode'] == 0 else {'status': 'timeout' if process['timed_out'] else 'agent_error', 'metrics': None})
            verifier = second.verify if package == 'itsdangerous' else repair.verify
            verified = verifier(grade['case'], grade['source_root'], grade['checks'], workspace, before,
                                case['allowed_files'], root, grade['python'], 15)
            accepted = result['status'] == 'completed' and verified['passed']
            report['runs'].append({'task_id': case['task_id'], 'policy': policy, 'worker': result, 'verification': verified,
                                  'accepted': accepted, 'process': process,
                                  'status': 'passed' if accepted else 'failed_verification' if result['status'] == 'completed' else result['status']})
            save()
            print(f"{case['task_id']} {policy}: {report['runs'][-1]['status']}", flush=True)
    frozen()
    pairs = {}
    for row in report['runs']:
        pairs.setdefault(row['task_id'], []).append(row['worker'].get('prompt_hash'))
    if any(len(values) != 2 or None in values or values[0] != values[1]
           for task, values in pairs.items()):
        raise ValueError('Unexpected context intervention or missing prompts')
    report['complete'] = len(report['runs']) == protocol['expected_runs']
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--task', action='append')
    parser.add_argument('--audit-only', action='store_true')
    args = parser.parse_args()
    if args.audit_only:
        if args.task:
            parser.error('Offline audit covers the complete public task set')
        audit(args.output)
    else:
        run(args.output, args.task)
