"""Fresh paired repairs using frozen Python line versus function evidence."""

import argparse
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

from docs.experiments import real_retrieval_audit_v1 as audit
from docs.experiments import retrieved_function_repair_v1 as patcher
from docs.experiments.vector_repair_v1 import check_identity, config
from evals.process import run_process
from evals.real_admission import checked_groups
from evals.real_tasks import admitted_case, verify
from evals.runner import digest, snapshot

OBS_SHA = 'd2367ad4330c4b83fe9921482fba4043e6640bbec521daad5dde88defb7b7479'
POLICIES = ('python-line-chunks', 'direct-functions')
MODEL_DIGEST = '7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e'


def validate_evidence(workspace, allowed, rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5:
        raise ValueError('Expected one to five frozen seeds')
    total = 0
    for row in rows:
        name = row['path']
        path = workspace / name
        if name not in allowed or path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
            raise ValueError('Evidence path is outside allowed source')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row['content_hash']:
            raise ValueError('Evidence source version changed')
        lines = data.decode('utf-8').splitlines(keepends=True)
        start, end = row['start_line'], row['end_line']
        if (type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines)
                or row['content'] != ''.join(lines[start - 1:end])):
            raise ValueError('Evidence citation does not match source')
        total += len(row['content'])
    if total > 6000:
        raise ValueError('Frozen evidence exceeds budget')


def prepare(source, output):
    if audit.sha(source / 'observations.json') != OBS_SHA:
        raise ValueError('Expected frozen function-index observations')
    prior = json.loads((source / 'protocol.json').read_text(encoding='utf-8'))
    if prior['protocol'] != 'function-index-audit-v1' or prior['engine_hash'] != audit.ENGINE:
        raise ValueError('Wrong frozen audit protocol')
    names = {'candidates.json': 'original', 'crossfile-candidates.json': 'crossfile',
             'expansion-candidates-v1.json': 'expansion'}
    admissions = {names[Path(c['catalog']).name]: Path(c['admission_path']) for c in prior['inputs']}
    cases = audit.public_cases(admissions)
    if output.exists() or any(output.resolve().is_relative_to(c['before'].parent.resolve()) for c in cases):
        raise ValueError('Use fresh output outside admitted sources')
    observations = json.loads((source / 'observations.json').read_text(encoding='utf-8'))
    if [c['task_id'] for c in cases] != [o['task_id'] for o in observations]:
        raise ValueError('Frozen task order mismatch')
    bundles = []
    for case, observation in zip(cases, observations):
        if observation['query'] != case['description'] + ' contract contracts':
            raise ValueError('Public query changed')
        if observation['index']['source_hash'] != observation['line_index']['source_hash']:
            raise ValueError('Python corpus mismatch')
        policies = {p: observation['policies'][p] for p in POLICIES}
        for policy in policies.values():
            validate_evidence(case['before'], case['allowed_files'], policy['evidence'])
        bundles.append({'task_id': case['task_id'], 'policies': policies})
    return cases, bundles


def summarize(runs):
    result = {}
    for policy in POLICIES:
        rows = [r for r in runs if r['policy'] == policy]
        metrics = [r['worker'].get('metrics') for r in rows]
        missing = sum(m is None for m in metrics)
        usage_missing = sum((m or {}).get('missing_usage_calls', 0) for m in metrics)
        known = sum((m or {}).get('budget_accounted_tokens', 0) for m in metrics)
        result[policy] = {'runs': len(rows), 'passed': sum(r['accepted'] for r in rows),
                          'statuses': dict(Counter(r['status'] for r in rows)),
                          'budget_accounted_tokens': known if not missing else None,
                          'known_budget_accounted_tokens': known, 'missing_metrics_runs': missing,
                          'missing_usage_calls': usage_missing,
                          'prompt_tokens': sum(m['prompt_tokens'] for m in metrics) if not missing and not usage_missing else None,
                          'completion_tokens': sum(m['completion_tokens'] for m in metrics) if not missing and not usage_missing else None,
                          'worker_seconds': round(sum(r['process']['seconds'] for r in rows), 4)}
    return result


def run(source, output):
    cases, bundles = prepare(source, output)
    check_identity(config())
    output.mkdir(parents=True)
    evidence_path = output / 'evidence.json'
    evidence_path.write_text(json.dumps(bundles, ensure_ascii=False, indent=2), encoding='utf-8')
    protocol = {'protocol': 'function-index-repair-v1', 'development_only': True, 'benchmark_eligible': False,
                'expected_runs': 14, 'observations_sha256': OBS_SHA, 'evidence_sha256': audit.sha(evidence_path),
                'engine_hash': audit.ENGINE, 'config': config().to_dict(), 'repair_model_digest': MODEL_DIGEST,
                'llm_calls_per_branch': 1, 'tools': [], 'dependency_depth': 0,
                'intervention': 'Python 40-line chunks versus complete function seeds; no dependencies or fallback',
                'worker_protocol': 'shared fragment patch worker; exact supplied old text and full-file version',
                'adapter_hashes': {p.relative_to(audit.ROOT).as_posix(): audit.sha(p)
                                   for p in (Path(__file__), Path(patcher.__file__), Path(audit.__file__))},
                'order': [{'task_id': c['task_id'], 'policies': list(POLICIES if i % 2 == 0 else POLICIES[::-1])}
                          for i, c in enumerate(cases)]}
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    # Validate every admitted failure before spending repair calls; parent only.
    admitted = []
    for case in cases:
        item = admitted_case(case['admission_path'], case['catalog'], case['task_id'])
        original_case, _, checks, source_root, environment = item
        python = Path(environment['executable'])
        preflight = checked_groups(case['before'], checks, output / 'preflight' / case['task_id'], python, 15)
        if not (preflight['Controls']['passed'] and preflight['Target']['assertion_failure']
                and not preflight['Target']['execution_error']):
            raise ValueError('Admitted behavior no longer reproduces')
        admitted.append((original_case, checks, source_root, python))
    report = {'protocol': protocol, 'complete': False, 'runs': []}

    def save():
        report['summary'] = summarize(report['runs'])
        (output / 'experiment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    save()
    for case, bundle, block, item in zip(cases, bundles, protocol['order'], admitted):
        original_case, checks, source_root, python = item
        for policy in block['policies']:
            check_identity(config())
            if audit.sha(evidence_path) != protocol['evidence_sha256'] or any(
                    audit.sha(audit.ROOT / p) != expected for p, expected in protocol['adapter_hashes'].items()):
                raise ValueError('Frozen evidence or adapter changed')
            root = output / case['task_id'] / policy
            workspace = root / 'workspace'
            root.mkdir(parents=True)
            shutil.copytree(case['before'], workspace)
            before = snapshot(workspace)
            if digest(before) != case['before_hash']:
                raise ValueError('Before source changed')
            evidence = bundle['policies'][policy]['evidence']
            validate_evidence(workspace, case['allowed_files'], evidence)
            job = {'workspace': str(workspace.resolve()), 'description': case['description'],
                   'allowed_files': case['allowed_files'], 'evidence': evidence}
            path = root / 'job.json'
            path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
            env = dict(os.environ, PYTHONPATH=str(audit.ROOT), PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
            process = run_process([sys.executable, '-m', 'docs.experiments.retrieved_function_repair_v1', '--worker', str(path.resolve())],
                                  workspace, 600, root / 'worker.stdout.txt', root / 'worker.stderr.txt', env)
            result_path = root / 'worker-result.json'
            result = (json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() and process['returncode'] == 0
                      and not process['timed_out'] else {'status': 'timeout' if process['timed_out'] else 'agent_error', 'metrics': None})
            verification = verify(original_case, source_root, checks, workspace, before, case['allowed_files'], root, python, 15)
            accepted = result['status'] == 'completed' and verification['passed']
            report['runs'].append({'task_id': case['task_id'], 'policy': policy, 'worker': result,
                                  'verification': verification, 'accepted': accepted,
                                  'status': 'passed' if accepted else ('failed_verification' if result['status'] == 'completed' else result['status']),
                                  'evidence_chars': sum(len(r['content']) for r in evidence), 'process': process})
            save()
            print(f"{case['task_id']} {policy}: {report['runs'][-1]['status']}", flush=True)
    check_identity(config())
    if any(digest(snapshot(c['before'])) != c['before_hash'] for c in cases):
        raise ValueError('Admitted snapshot changed during repairs')
    report['complete'] = len(report['runs']) == protocol['expected_runs']
    save()
    print(json.dumps(report['summary'], indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.source.resolve(), args.output.resolve())


if __name__ == '__main__':
    main()
