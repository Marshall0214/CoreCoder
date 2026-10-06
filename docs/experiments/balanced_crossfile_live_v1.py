"""Cross-file frozen-pool transfer test of unchanged balanced interval packing."""

import argparse
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from docs.experiments.balanced_interval_live_v1 import patch
from docs.experiments.staged_compact_live_v1 import check_code, check_model
from evals.process import run_process
from evals.real_admission import DATA, checked_groups, execute
from evals.real_suite import file_hash
from evals.real_tasks import admitted_case, verify, visible_checks
from evals.runner import digest, snapshot
from evals.runtime import BudgetLLM, Events
from evals.schema import RunConfig, relative_path
from evals.staged_repair import validate_localization
from evals.worker import TracedLLM, ollama_metadata

PROTOCOL_PATH = Path(__file__).with_suffix('.json')


def load_inputs(protocol):
    if (protocol['purpose'] != 'balanced-crossfile-patch-development-v1' or protocol['benchmark_eligible']
            or protocol['order'] != ['baseline', 'balanced'] or protocol['expected_patch_runs'] != 2
            or protocol['expected_new_localizations'] != 0):
        raise ValueError('Unexpected definition patch protocol')
    check_code(protocol)
    for name, expected in protocol['input_files'].items():
        if file_hash(ROOT / relative_path(name)) != expected:
            raise ValueError('Frozen input changed')
    case = admitted_case(ROOT / relative_path(protocol['admission']), DATA / relative_path(protocol['catalog']), protocol['task_id'])
    checkpoints = {}
    for policy in protocol['order']:
        record = protocol['checkpoints'][policy]
        path = ROOT / relative_path(record['path'])
        if file_hash(path) != record['sha256']:
            raise ValueError('Frozen checkpoint changed')
        checkpoint = json.loads(path.read_text(encoding='utf-8'))
        if checkpoint['checkpoint_hash'] != record['checkpoint_hash']:
            raise ValueError('Checkpoint identity changed')
        config = RunConfig(**checkpoint['config'])
        validate_localization(checkpoint, case[3] / 'before', case[0]['public_problem'], checkpoint['allowed_files'], config)
        if checkpoint['localization_result']['candidate_pool_hash'] != record['candidate_pool_hash']:
            raise ValueError('Candidate identity changed')
        if checkpoint['metrics']['budget_accounted_tokens'] != record['localization_tokens']:
            raise ValueError('Localization cost changed')
        checkpoints[policy] = checkpoint
    baseline, definition = (checkpoints[k] for k in protocol['order'])
    for key in ('description', 'allowed_files', 'source_hashes', 'config'):
        if baseline[key] != definition[key]:
            raise ValueError('Paired inputs differ outside localization evidence')
    if baseline['checkpoint_hash'] != definition['checkpoint_hash']:
        raise ValueError('Packing comparison requires one identical checkpoint')
    return case, RunConfig(**baseline['config']), checkpoints




def worker(job_path):
    job = json.loads(job_path.read_text(encoding='utf-8'))
    config = RunConfig(**job['config'])
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding='utf-8'))
    events = Events(job_path.parent / 'trace.jsonl', job['run_id'])
    result, llm = {'status': 'agent_error', 'metrics': None}, None
    try:
        if file_hash(PROTOCOL_PATH) != job['protocol_sha256']:
            raise ValueError('Protocol changed between parent and worker')
        check_code(protocol)
        checkpoint = job['checkpoint']
        if checkpoint['checkpoint_hash'] != protocol['checkpoints'][job['policy']]['checkpoint_hash']:
            raise ValueError('Unexpected task checkpoint')
        workspace = Path(job['workspace'])
        validate_localization(checkpoint, workspace, checkpoint['description'], checkpoint['allowed_files'], config)
        result['ollama_before'] = check_model(config, protocol)
        extra = {'temperature': config.temperature, 'max_tokens': config.max_output_tokens,
                 'timeout': min(60, config.wall_timeout), 'reasoning_effort': config.reasoning_effort}
        llm = BudgetLLM(TracedLLM(config.model, 'ollama', config.base_url, events=events, **extra), config, events)
        result.update(patch(llm, workspace, checkpoint, config, events,
                            'read-first' if job['policy'] == 'baseline' else 'public-balanced-v1',
                            protocol['bare_names']))
        result['localization_policy'] = job['policy']
        result['public_verification'] = execute(workspace, workspace / '.real-visible', 'Controls',
                                                job_path.parent / 'public-logs', Path(job['python']), config.test_timeout)
    except Exception as exc:  # noqa: BLE001 - persist failed workers for independent grading
        result.update(error=f'{type(exc).__name__}: {exc}')
    finally:
        if llm:
            result['metrics'] = llm.metrics()
            result['ollama_after'] = ollama_metadata(config)
        (job_path.parent / 'worker-result.json').write_text(json.dumps(events.clean(result), ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


def branch(case, config, output, checkpoint, policy, protocol_sha):
    task, admission, checks, source_root, environment = case
    root = output / (task['case_id'] + '-' + uuid.uuid4().hex[:10])
    root.mkdir(parents=True, exist_ok=False)
    result = {'task_id': task['case_id'], 'policy': policy, 'accepted': False, 'status': 'infrastructure_error',
              'metrics': None, 'artifacts': str(root), 'verification': None}
    started = time.perf_counter()
    try:
        python = Path(environment['executable'])
        preflight = checked_groups(source_root / 'before', checks, root / 'preflight', python, config.test_timeout)
        if not (preflight['Controls']['passed'] and preflight['Target']['assertion_failure']
                and not preflight['Target']['passed'] and not preflight['Target']['execution_error']):
            raise ValueError('Original behavior changed')
        workspace = root / 'workspace'
        shutil.copytree(source_root / 'before', workspace)
        public = workspace / '.real-visible'
        public.mkdir()
        (public / 'test_admission.py').write_text(visible_checks(checks), encoding='utf-8')
        original = snapshot(workspace)
        allowed = sorted(name for name in original if name.startswith('src/click/') and name.endswith('.py'))
        validate_localization(checkpoint, workspace, task['public_problem'], allowed, config)
        job = {'run_id': root.name, 'task_id': task['case_id'], 'workspace': str(workspace), 'python': str(python),
               'checkpoint': checkpoint, 'config': config.to_dict(), 'policy': policy, 'protocol_sha256': protocol_sha}
        job_path = root / 'job.json'
        job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
        env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        execution = run_process([sys.executable, str(Path(__file__).resolve()), '--worker', str(job_path)], workspace,
                                config.wall_timeout, root / 'worker.stdout.txt', root / 'worker.stderr.txt', env)
        worker_path = root / 'worker-result.json'
        outcome = ({'status': 'timeout', 'metrics': None} if execution['timed_out'] else
                   {'status': 'agent_error', 'metrics': None} if execution['returncode'] != 0 or not worker_path.exists()
                   else json.loads(worker_path.read_text(encoding='utf-8')))
        result.update(worker=outcome, metrics=outcome['metrics'], fixture_hash=digest(original),
                      visible_checks_hash=digest(snapshot(public)), admission_checks_hash=admission['checks_hash'])
        if digest(snapshot(checks)) != admission['checks_hash']:
            raise ValueError('Parent checks changed')
        for label in ('before', 'after'):
            if digest(snapshot(source_root / label)) != admission['revisions'][label]['tree_hash']:
                raise ValueError('Admitted source changed')
        result['verification'] = verify(task, source_root, checks, workspace, original, allowed, root, python, config.test_timeout)
        result['accepted'] = outcome['status'] == 'completed' and result['verification']['passed']
        result['status'] = ('passed' if result['accepted'] else 'failed_verification'
                            if outcome['status'] == 'completed' else outcome['status'])
    except KeyboardInterrupt:
        result['status'] = 'cancelled'
    except Exception as exc:  # noqa: BLE001 - failed runs remain in the denominator
        result['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        result['seconds'] = round(time.perf_counter() - started, 4)
        (root / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker.resolve())
    if not args.output:
        parser.error('--output is required')
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding='utf-8'))
    case, config, checkpoints = load_inputs(protocol)
    output = args.output.resolve()
    protected = [case[2], case[3], *(ROOT / record['path'] for record in protocol['checkpoints'].values())]
    if output.exists() or any(output.is_relative_to(p.resolve()) or p.resolve().is_relative_to(output) for p in protected):
        raise ValueError('Use fresh output outside frozen source, checks and inputs')
    if args.validate_only:
        print('Validated cross-file shared pool; unchanged read-first/balanced policies, no model calls')
        return 0
    check_model(config, protocol)
    output.mkdir(parents=True)
    protocol_sha = file_hash(PROTOCOL_PATH)
    report = {'protocol': protocol, 'protocol_sha256': protocol_sha, 'config': config.to_dict(),
              'benchmark_eligible': False, 'complete': False, 'new_localizations': 0, 'patch_runs': []}
    for policy in protocol['order']:
        load_inputs(protocol)
        check_model(config, protocol)
        if file_hash(PROTOCOL_PATH) != protocol_sha:
            raise ValueError('Protocol changed during run')
        row = branch(case, config, output / policy, checkpoints[policy], policy, protocol_sha)
        report['patch_runs'].append(row)
        (output / 'experiment.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(policy, row['status'], flush=True)
        if row['status'] == 'cancelled':
            return 1
    load_inputs(protocol)
    check_model(config, protocol)
    if file_hash(PROTOCOL_PATH) != protocol_sha:
        raise ValueError('Protocol changed at completion')
    report['complete'] = len(report['patch_runs']) == 2
    report['actual_new_patch_tokens'] = sum((r['metrics'] or {}).get('budget_accounted_tokens', 0) for r in report['patch_runs'])
    report['shared_actual_localization_tokens'] = checkpoints['baseline']['metrics']['budget_accounted_tokens']
    report['pipeline_tokens'] = sum((r.get('worker', {}).get('budget_accounting', {})
                                   .get('pipeline_equivalent_tokens', 0)) for r in report['patch_runs'])
    report['historical_plus_new_actual_tokens'] = report['actual_new_patch_tokens'] + report['shared_actual_localization_tokens']
    report['cost_note'] = 'pipeline_tokens sums standalone branch equivalents; shared localization is counted once in historical_plus_new_actual_tokens.'
    report['known_usage_only'] = True
    hashes = [r.get('worker', {}).get('patch_non_evidence_hash') for r in report['patch_runs']]
    report['same_non_evidence_prompt'] = bool(hashes[0]) and hashes[0] == hashes[1]
    (output / 'experiment.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output / 'experiment.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
