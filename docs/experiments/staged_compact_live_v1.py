"""Explicit frozen-pool patch experiment; isolated workers and independent parent grading."""

import argparse
import json
import os
import shutil
import sys
import time
import uuid
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from corecoder.config import _load_dotenv
from docs.experiments.staged_compact_packing_v1 import compact_evidence
from evals.process import run_process
from evals.real_admission import DATA, checked_groups, execute
from evals.real_suite import file_hash, load_manifest, prepare
from evals.real_tasks import verify, visible_checks
from evals.runner import digest, implementation_metadata, snapshot
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.schema import RunConfig, relative_path
from evals.staged_repair import object_hash, select_evidence, validate_localization
from evals.symbol_context import apply_symbol_patch
from evals.symbol_patch import SYMBOL_SYSTEM
from evals.worker import TracedLLM, ollama_metadata

PROTOCOL_PATH = Path(__file__).with_suffix('.json')


def check_code(protocol):
    if implementation_metadata()['source_hash'] != protocol['implementation_sha256']:
        raise ValueError('Frozen repair implementation changed')
    for name, expected in protocol['adapter_files'].items():
        if file_hash(ROOT / relative_path(name)) != expected:
            raise ValueError('Frozen experiment adapter changed')


def check_model(config, protocol):
    metadata = ollama_metadata(config)
    models = (metadata or {}).get('identity', {}).get('models', [])
    if not any(row['name'] == config.model and row['digest'] == protocol['model_digest'] for row in models):
        raise ValueError('Frozen model unavailable or changed')
    return metadata


def patch(llm, workspace, checkpoint, config, events, policy):
    if policy not in {'read-first', 'compact-read-first-v1'}:
        raise ValueError('Unknown experiment policy')
    validate_localization(checkpoint, workspace, checkpoint['description'], checkpoint['allowed_files'], config)
    if llm.spent:
        raise ValueError('Patch replay requires a fresh counter')
    pool = checkpoint['pool']
    packing = None
    if policy == 'read-first':
        evidence = select_evidence(pool['reads'], pool['seeds'], config.search_max_chars)
    else:
        sources = {name: (workspace / relative_path(name)).read_bytes() for name in checkpoint['allowed_files']}
        evidence, packing = compact_evidence(pool['reads'], pool['seeds'], sources, config.search_max_chars)
    shared = checkpoint['metrics']['budget_accounted_tokens']
    limits = checkpoint['localization_result']['stage_limits']
    available = min(limits['patch'], max(0, config.token_budget - shared - limits['verification_reserve']))
    payload = {'description': checkpoint['description'], 'allowed_files': checkpoint['allowed_files'], 'fragments': evidence,
               'budget_state': {'patch_tokens': available, 'verification_reserve': limits['verification_reserve']},
               'instruction': 'Localization has ended. Return evidence-supported edits now, or an empty edits array. '
                              'Repair every behavior in the public description and preserve normal behavior.'}
    messages = [{'role': 'system', 'content': SYMBOL_SYSTEM},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]
    result = {'status': 'agent_error', 'policy': policy, 'candidate_pool_hash': object_hash(pool),
              'localization_checkpoint_hash': checkpoint['checkpoint_hash'], 'shared_tokens': shared,
              'evidence_hash': object_hash(evidence), 'patch_prompt_hash': object_hash(messages),
              'patch_non_evidence_hash': object_hash({'system': SYMBOL_SYSTEM,
                                                     'payload': {k: v for k, v in payload.items() if k != 'fragments'}}),
              'evidence_chars': sum(len(row['content']) for row in evidence),
              'message_json_chars': len(json.dumps(messages, ensure_ascii=False)), 'packing': packing}
    (events.path.parent / 'patch-request.json').write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding='utf-8')
    original_config = llm.config
    events.emit('localization_replayed', actual_localization_calls=0, shared_tokens=shared,
                checkpoint_hash=checkpoint['checkpoint_hash'])
    try:
        if not evidence or available < 1:
            raise BudgetExceeded('No evidence or available patch budget')
        llm.config = replace(config, token_budget=available, output_policy='remaining')
        response = llm.chat(messages, tools=[])
        (events.path.parent / 'staged-patch-response.txt').write_text(events.clean(response.content), encoding='utf-8')
        if response.tool_calls:
            raise ValueError('Patch request accepts JSON edits only')
        result['edited_files'] = apply_symbol_patch(response.content, workspace, checkpoint['allowed_files'], evidence)
        result['status'] = 'completed'
    except BudgetExceeded as exc:
        result.update(status='budget_exceeded', error=str(exc))
    except (ValueError, TypeError, KeyError, OSError) as exc:
        result.update(status='invalid_patch', error=f'{type(exc).__name__}: {exc}')
    finally:
        llm.config = original_config
    result['budget_accounting'] = {'actual_worker_tokens': llm.spent, 'patch_tokens': llm.spent,
                                   'shared_localization_tokens': shared, 'pipeline_equivalent_tokens': shared + llm.spent,
                                   'shared_localization_executed_here': False}
    return result


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
        if checkpoint['checkpoint_hash'] != protocol['checkpoints'][job['task_id']]['checkpoint_hash']:
            raise ValueError('Unexpected task checkpoint')
        workspace = Path(job['workspace'])
        validate_localization(checkpoint, workspace, checkpoint['description'], checkpoint['allowed_files'], config)
        result['ollama_before'] = check_model(config, protocol)
        extra = {'temperature': config.temperature, 'max_tokens': config.max_output_tokens,
                 'timeout': min(60, config.wall_timeout), 'reasoning_effort': config.reasoning_effort}
        llm = BudgetLLM(TracedLLM(config.model, 'ollama', config.base_url, events=events, **extra), config, events)
        result.update(patch(llm, workspace, checkpoint, config, events, job['policy']))
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
    parser.add_argument('--admission', action='append', metavar='SOURCE=PATH')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker.resolve())
    if not args.admission or not args.output:
        parser.error('--admission and --output are required for parent execution')
    admissions = {}
    for item in args.admission:
        name, separator, path = item.partition('=')
        if not separator or not path or name in admissions:
            parser.error('Supply unique SOURCE=PATH admissions')
        admissions[name] = Path(path).resolve()
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding='utf-8'))
    manifest = DATA / relative_path(protocol['manifest'])
    if (protocol['purpose'] != 'development-compact-frozen-patch-v1' or protocol['expected_patch_runs'] != 14
            or protocol['expected_new_localizations'] != 0 or file_hash(manifest) != protocol['manifest_sha256']):
        raise ValueError('Unexpected compact experiment protocol')
    check_code(protocol)
    data, entries = load_manifest(manifest)
    cases = prepare(entries, admissions)
    config = RunConfig(**data['config'])
    if (len(cases) != 7 or set(protocol['checkpoints']) != {case[0]['case_id'] for case in cases}
            or set(protocol['order']) != set(protocol['checkpoints'])
            or any(len(policies) != 2 or set(policies) != {'read-first', 'compact-read-first-v1'}
                   for policies in protocol['order'].values())):
        raise ValueError('Expected seven tasks with two distinct policies each')
    checkpoints = {}
    for case in cases:
        task = case[0]['case_id']
        record = protocol['checkpoints'][task]
        path = ROOT / relative_path(record['path'])
        if not path.resolve().is_relative_to(ROOT) or file_hash(path) != record['sha256']:
            raise ValueError('Frozen checkpoint changed')
        checkpoint = json.loads(path.read_text(encoding='utf-8'))
        validate_localization(checkpoint, case[3] / 'before', case[0]['public_problem'], checkpoint['allowed_files'], config)
        checkpoints[task] = checkpoint
    output = args.output.resolve()
    if output.exists() or any(output.is_relative_to(p.resolve()) for case in cases for p in case[2:4]):
        raise ValueError('Use a fresh output outside admitted source and checks')
    if any(output.is_relative_to((ROOT / record['path']).parent.resolve()) for record in protocol['checkpoints'].values()):
        raise ValueError('Output must stay outside frozen checkpoints')
    _load_dotenv()
    check_model(config, protocol)
    if args.validate_only:
        print('Validated: 7 frozen pools, 14 patch branches, separate adapter hashes, no new localization')
        return 0
    output.mkdir(parents=True, exist_ok=False)
    protocol_sha = file_hash(PROTOCOL_PATH)
    report = {'protocol': protocol, 'protocol_sha256': protocol_sha, 'config': config.to_dict(),
              'benchmark_eligible': False, 'complete': False, 'new_localizations': 0, 'patch_runs': []}
    for case in cases:
        task = case[0]['case_id']
        for policy in protocol['order'][task]:
            check_code(protocol)
            check_model(config, protocol)
            for record in protocol['checkpoints'].values():
                if file_hash(ROOT / record['path']) != record['sha256']:
                    raise ValueError('Checkpoint changed between branches')
            if file_hash(PROTOCOL_PATH) != protocol_sha:
                raise ValueError('Protocol changed during experiment')
            row = branch(case, config, output / policy, checkpoints[task], policy, protocol_sha)
            report['patch_runs'].append(row)
            (output / 'experiment.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(task, policy, row['status'], flush=True)
            if row['status'] == 'cancelled':
                return 1
    check_code(protocol)
    check_model(config, protocol)
    if file_hash(PROTOCOL_PATH) != protocol_sha or any(file_hash(ROOT / row['path']) != row['sha256']
                                                      for row in protocol['checkpoints'].values()):
        raise ValueError('Protocol or checkpoint changed at completion')
    report['complete'] = len(report['patch_runs']) == 14
    (output / 'experiment.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output / 'experiment.json', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
