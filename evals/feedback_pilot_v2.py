"""Five known local development cases: fresh exploration, feedback, then private grading."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from evals import local50
from evals.ollama_input_logs import classify
from evals.process import terminate_tree
from evals.runner import changes, digest, snapshot
from evals.swebench_batch import environment, save
from evals.swebench_mini import ROOT, sha
from repairflow.patch_validator import group_passed, inside, permitted

PROTOCOL = 'feedback-actions-pilot-five-v1'
TASK_IDS = ('toolz-join-unmatched', 'itsdangerous-none-salt', 'boltons-split-zero',
            'click-style-color-validation', 'more-negative-range-slice')
CODE = ('evals/feedback_pilot_v2.py', 'evals/local50.py', 'evals/local50_unmetered.py',
        'evals/repository_checkpoint.py', 'evals/swebench_agent.py', 'evals/runtime.py',
        'evals/context_policy.py', 'evals/process.py', 'evals/swebench_batch.py', 'evals/runner.py',
        'evals/ollama_input_logs.py',
        'corecoder/context.py', 'repairflow/feedback_repair_v2.py', 'repairflow/feedback_actions.py',
        'repairflow/feedback_context.py', 'repairflow/feedback_observability.py',
        'repairflow/issue_providers.py', 'repairflow/issue_tools.py', 'repairflow/checks.py',
        'repairflow/patch_validator.py', 'repairflow/telemetry.py', 'sandbox/runner.py',
        'deploy/langfuse/feedback_pilot.py')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def check_case(case):
    for key in ('before', 'after', 'harness', 'checks'):
        path = inside(Path(case[key]))
        if digest(snapshot(path)) != case[key + '_hash']:
            raise ValueError('Frozen input changed: ' + case['task_id'] + '/' + key)


def prepare(output, manifest=local50.MANIFEST):
    output = inside(output)
    if not output.is_relative_to(ROOT / '.tmp'):
        raise ValueError('Use a fresh project .tmp directory on D:')
    records = read(manifest)['cases']
    keys = ('task_id', 'repo', 'package', 'source_root', 'description', 'allowed_files',
            'before', 'after', 'harness', 'checks', 'before_hash', 'after_hash', 'harness_hash', 'checks_hash')
    cases = []
    for task_id in TASK_IDS:
        matches = [row for row in records if row['task_id'] == task_id]
        if len(matches) != 1:
            raise ValueError('Require exactly one frozen case: ' + task_id)
        case = {key: matches[0][key] for key in keys}
        check_case(case)
        cases.append(case)
    output.mkdir(parents=True, exist_ok=False)
    protocol = {'name': PROTOCOL, 'task_ids': list(TASK_IDS), 'cases': cases,
                'manifest': str(Path(manifest).resolve()), 'manifest_sha256': sha(manifest),
                'model': 'qwen3.5:27b', 'thinking': False, 'token_budget': None, 'max_output_tokens': None,
                'initial_max_requests': 20, 'initial_max_edits': 6, 'feedback_max_requests': 20,
                'initial_seconds': 1200, 'feedback_seconds': 1200, 'model_call_seconds': 480,
                'feedback_context_estimated_target': 12000, 'provider_context_tokens': 65536,
                'strategy_search': False, 'reuse_old_candidates': False,
                'scope': 'Five known hand-authored development cases; not an unseen benchmark or a controlled improvement claim',
                'independent_grading': 'Controller only after feedback process termination',
                'source_files': {name: sha(ROOT / name) for name in CODE}}
    save(output / 'protocol.json', protocol)
    for name in CODE:
        destination = output / 'implementation' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    save(output / 'report.json', {'status': 'prepared', 'protocol_sha256': sha(output / 'protocol.json'),
                                 'tasks': {}, 'admission': {}, 'summary': {}})
    return protocol


def candidate_input(folder, case):
    """Merge a verified text-export patch back into a complete private baseline copy."""
    agent = folder / 'initial/agent'
    report = read(agent / 'report.json')
    baseline = snapshot(folder / 'baseline')
    inventory = read(agent / 'baseline-files.json')
    if any(name not in baseline or hashlib.sha256(baseline[name]).hexdigest() != value
           for name, value in inventory.items()):
        raise ValueError('Exploration export does not match the full baseline')
    current = snapshot(agent / 'workspace')
    changed, patch = changes({name: baseline[name] for name in inventory}, current)
    if (changed != report['changed_files'] or sha(agent / 'patch.diff') != report['patch_sha256']
            or patch != (agent / 'patch.diff').read_bytes().decode('utf-8')
            or any(name not in current or name not in case['allowed_files'] for name in changed)):
        raise ValueError('Exploration candidate was changed or exceeded edit permissions')
    output = folder / 'candidate-input'
    expected = dict(baseline)
    expected.update({name: current[name] for name in changed})
    if output.exists():
        if snapshot(output) != expected:
            raise ValueError('Saved candidate input differs from the verified exploration patch')
        return output
    shutil.copytree(folder / 'baseline', output)
    for name in changed:
        (output / name).write_bytes(current[name])
    return output


def feedback_worker(job_path):
    from evals.swebench_agent import AgentTelemetry
    from repairflow.feedback_observability import ObservedFeedbackLLM
    from repairflow.feedback_repair_v2 import run
    from repairflow.issue_providers import OllamaProvider
    from repairflow.telemetry import ObservedEvents

    job, folder = read(job_path), job_path.parent
    task = read(Path(job['public_task']))
    if sha(Path(job['public_task'])) != job['public_task_sha256']:
        raise ValueError('Public task changed')
    for key in ('baseline', 'candidate', 'public_checks'):
        if digest(snapshot(Path(job[key]))) != job[key + '_hash']:
            raise ValueError('Feedback public input changed: ' + key)
    observer = AgentTelemetry(folder / 'feedback', {**task, 'source_sha256': job['baseline_hash'],
                              'harness_sha256': job['public_checks_hash']}, 'ollama', 'qwen3.5:27b')
    if observer.root is not None:
        try:
            observer.root.update(metadata={**{key: job[key] for key in
                ('experiment_id', 'task_id', 'protocol', 'phase', 'attempt')}, 'pilot_phase': 'feedback'})
        except Exception as exc:  # noqa: BLE001 - optional telemetry
            observer._error(exc)
    events = ObservedEvents(folder / 'feedback-trace.jsonl', folder.name + '/feedback', observer)
    llm = ObservedFeedbackLLM(OllamaProvider('qwen3.5:27b', time.monotonic() + 1200), events)
    result = {'status': 'worker_failed', 'fresh_model_calls': 0, 'changed_files': []}
    try:
        result = run(Path(job['baseline']), Path(job['candidate']), job['allowed_files'],
                     Path(job['public_checks']), job['package'], task, folder / 'feedback',
                     source_root=job['source_root'], readable_files=job['readable_files'], llm=llm,
                     context_contract=True, max_feedback_rounds=20, timeout=1200, events=events)
    finally:
        result.update(fresh_model_calls=llm.calls, metrics=llm.metrics(), execution_mode='ollama')
        result['observability'] = observer.finish(result)
        if (folder / 'feedback').exists():
            save(folder / 'feedback/report.json', result)


def initial_worker(job_path):
    from evals import local50_unmetered

    job = read(job_path)
    original = local50.AgentTelemetry

    class PilotTelemetry(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if self.root is not None:
                try:
                    self.root.update(metadata={key: job[key] for key in
                        ('experiment_id', 'task_id', 'protocol', 'pilot_phase', 'attempt')})
                except Exception as exc:  # noqa: BLE001 - optional telemetry
                    self._error(exc)

    try:
        local50.AgentTelemetry = PilotTelemetry
        local50_unmetered.worker(job_path)
    finally:
        local50.AgentTelemetry = original


def phase_usage(report, phase):
    measured = report['metrics'] or (aggregate_usage([]) if report['fresh_model_calls'] == 0 else {})
    return {'phase': phase, 'fresh_model_calls': report['fresh_model_calls'], 'metrics': measured,
            'trace_id': report.get('observability', {}).get('trace_id')}


def aggregate_usage(phases):
    calls = sum(row['fresh_model_calls'] for row in phases)
    missing = sum(row['metrics'].get('missing_usage_calls', row['fresh_model_calls']) for row in phases)
    prompt = sum(row['metrics'].get('known_prompt_tokens', 0) for row in phases)
    completion = sum(row['metrics'].get('known_completion_tokens', 0) for row in phases)
    return {'llm_calls': calls, 'missing_usage_calls': missing,
            'known_prompt_tokens': prompt, 'known_completion_tokens': completion,
            'known_tokens_minimum': prompt + completion,
            'prompt_tokens': prompt if missing == 0 else None,
            'completion_tokens': completion if missing == 0 else None,
            'usage_status': 'not_applicable' if not calls else 'known' if not missing else 'partial',
            'token_budget': None}


def trace_usage(path, phase):
    """Recover known costs even when a killed worker leaves no terminal report."""
    calls = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue  # A hard termination can leave one partial trailing record.
            if row.get('event') in {'llm_started', 'llm_finished', 'llm_failed'}:
                call = calls.setdefault(row['call_id'], {})
                if row['event'] != 'llm_started':
                    call.update(row)
    prompt = sum(row.get('prompt_tokens') or 0 for row in calls.values())
    completion = sum(row.get('completion_tokens') or 0 for row in calls.values())
    missing = sum(any(type(row.get(key)) is not int for key in ('prompt_tokens', 'completion_tokens'))
                  for row in calls.values())
    return {'phase': phase, 'fresh_model_calls': len(calls), 'trace_id': None, 'recovered_from_trace': True,
            'metrics': {'llm_calls': len(calls), 'known_prompt_tokens': prompt, 'known_completion_tokens': completion,
                        'prompt_tokens': prompt if not missing else None,
                        'completion_tokens': completion if not missing else None, 'missing_usage_calls': missing}}


def log_position():
    path = Path(os.environ.get('LOCALAPPDATA', '')) / 'Ollama/server.log'
    return {'path': str(path), 'size': path.stat().st_size if path.is_file() else None}


def log_evidence(before, output):
    path = Path(before['path'])
    result = {'before': before, 'server_input_truncation': 'not_verified',
              'scope': 'Local server log slice; absence of a warning is not proof of complete input'}
    if before['size'] is not None and path.is_file() and path.stat().st_size >= before['size']:
        with path.open('rb') as stream:
            stream.seek(before['size'])
            raw = stream.read(8_000_001)
        result.update(slice_bytes=len(raw), slice_sha256=hashlib.sha256(raw).hexdigest(),
                      collection_complete=len(raw) <= 8_000_000)
        classified = classify(raw.decode('utf-8', errors='replace'))
        result.update(classified, truncation_warnings=classified['confirmed_input_truncation_warnings'])
    else:
        result['log_status'] = 'unavailable_or_rotated'
    save(output, result)
    return result


def launch(module, args, folder, batch, phase, timeout=1350):
    from sandbox import runner

    env = environment('agent', batch)
    env['CORECODER_TEST_BACKEND'] = 'docker'
    kwargs = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    before = log_position()
    with (folder / (phase + '.log')).open('ab') as stream:
        process = subprocess.Popen([sys.executable, '-B', '-m', module, *map(str, args)], cwd=ROOT,
                                   env=env, stdout=stream, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kwargs)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if (batch / 'CANCEL').exists() or time.monotonic() >= deadline:
                    terminate_tree(process)
                    raise RuntimeError('Cancelled or worker deadline exceeded; no automatic inference retry')
                time.sleep(0.2)
        except BaseException:
            if process.poll() is None:
                terminate_tree(process)
            if phase == 'feedback':
                runner.cleanup(folder / 'feedback')
            raise
        finally:
            log_evidence(before, folder / (phase + '-input-evidence.json'))
    if process.returncode:
        raise RuntimeError(phase + ' worker failed; see saved log')


def summarize(tasks):
    phases = [phase for row in tasks.values() for phase in row.get('phases', [])]
    graded = [row for row in tasks.values() if row.get('status') == 'graded']
    return {'scheduled': len(TASK_IDS), 'graded': len(graded), 'resolved': sum(row['resolved'] for row in graded),
            'public_accepted': sum(row.get('public_accepted', False) for row in tasks.values()),
            'infra_errors': sum(row.get('status') == 'infra_error' for row in tasks.values()),
            'fresh_model_calls': sum(row['fresh_model_calls'] for row in phases), 'metrics': aggregate_usage(phases)}


def model_identity():
    import urllib.request

    from repairflow.github_issue import NoRedirect

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open('http://127.0.0.1:11434/api/tags', timeout=10) as response:
        tags = json.loads(response.read(1_000_001))
    selected = next(row for row in tags['models'] if row['name'] == 'qwen3.5:27b')
    return {'model': selected['name'], 'digest': selected['digest']}


def execute(output, *, resume=False, prepare_only=False):
    from repairflow.checks import groups, verify
    from sandbox import runner

    output = inside(output)
    protocol = read(output / 'protocol.json') if resume else prepare(output)
    if protocol['name'] != PROTOCOL or protocol['task_ids'] != list(TASK_IDS):
        raise ValueError('Resume only this fixed five-case protocol')
    if sha(Path(protocol['manifest'])) != protocol['manifest_sha256'] or any(
            sha(ROOT / name) != value for name, value in protocol['source_files'].items()):
        raise ValueError('Frozen protocol implementation or manifest changed')
    os.environ['CORECODER_TEST_BACKEND'] = 'docker'
    policy = runner.preflight()
    runner.ACTIVE_POLICY.set(policy)
    identity = {**model_identity(), 'sandbox': policy}
    if (output / 'identity.json').exists() and read(output / 'identity.json') != identity:
        raise ValueError('Local model or sandbox identity changed')
    save(output / 'identity.json', identity)
    report = read(output / 'report.json')
    if report['protocol_sha256'] != sha(output / 'protocol.json'):
        raise ValueError('Run report does not match the frozen protocol')
    # Certify all public and independent environments before spending inference.
    for case in protocol['cases']:
        check_case(case)
        folder = output / 'tasks' / case['task_id']
        folder.mkdir(parents=True, exist_ok=True)
        if case['task_id'] not in report['admission']:
            public = {name: groups(case[name], case['harness'], case['package'], case['source_root'],
                                   folder / ('admission-public-' + name), ('Reproduce', 'Preserve'))
                      for name in ('before', 'after')}
            if (group_passed(public['before']['Reproduce']) or not group_passed(public['before']['Preserve'])
                    or not all(group_passed(row) for row in public['after'].values())):
                raise ValueError('Public fixture admission failed: ' + case['task_id'])
            private = local50.fixture_controls(case, folder)
            report['admission'][case['task_id']] = {'passed': True, 'public': public, 'private': private}
            save(output / 'report.json', report)
            print('admission ' + case['task_id'] + ': passed', flush=True)
    if prepare_only:
        report['status'] = 'admitted'
        save(output / 'report.json', report)
        return report
    for case in protocol['cases']:
        key = case['task_id']
        state = report['tasks'].setdefault(key, {'status': 'prepared', 'phases': [], 'fresh_model_calls': 0,
                                               'metrics': aggregate_usage([])})
        if state['status'] in {'graded', 'infra_error'}:
            continue
        if (output / 'CANCEL').exists():
            report['status'] = 'cancelled'
            break
        if model_identity() != {k: identity[k] for k in ('model', 'digest')}:
            raise ValueError('Local model changed before task')
        folder = output / 'tasks' / key
        phase = 'prepare'
        try:
            if not (folder / 'baseline').exists():
                shutil.copytree(case['before'], folder / 'baseline')
                shutil.copytree(case['harness'], folder / 'public-checks')
            public = {'instance_id': key, 'repo': case['repo'], 'base_commit': 'source-sha256:' + case['before_hash'],
                      'problem_statement': case['description']}
            save(folder / 'public.json', public)
            initial = folder / 'initial'
            initial.mkdir(exist_ok=True)
            save(initial / 'public.json', public)
            save(initial / 'job.json', {'source': str(folder / 'baseline'), 'source_hash': case['before_hash'],
                                       'public_sha256': sha(initial / 'public.json'),
                                       'experiment_id': output.name, 'task_id': key, 'protocol': PROTOCOL,
                                       'pilot_phase': 'initial', 'attempt': 1})
            phase = 'initial'
            state['status'] = 'running_initial'
            save(output / 'report.json', report)
            print(key + ': initial started', flush=True)
            if not (initial / 'agent/report.json').exists():
                if (initial / 'agent').exists():
                    raise ValueError('Interrupted initial run; no automatic inference replay')
                launch('evals.feedback_pilot_v2', ['--initial-worker', initial / 'job.json'], folder, output, phase)
            first = read(initial / 'agent/report.json')
            state['phases'] = [phase_usage(first, phase)]
            state['initial_status'] = first['status']
            state['metrics'] = aggregate_usage(state['phases'])
            save(output / 'report.json', report)
            candidate_input(folder, case)
            candidate = folder / 'candidate-input'
            job = {'baseline': str(folder / 'baseline'), 'baseline_hash': case['before_hash'],
                   'candidate': str(candidate), 'candidate_hash': digest(snapshot(candidate)),
                   'public_checks': str(folder / 'public-checks'), 'public_checks_hash': case['harness_hash'],
                   'package': case['package'], 'source_root': case['source_root'],
                   'allowed_files': case['allowed_files'],
                   'readable_files': [name for name in snapshot(candidate) if permitted(name)],
                   'public_task': str(folder / 'public.json'), 'public_task_sha256': sha(folder / 'public.json'),
                   'experiment_id': output.name, 'task_id': key, 'protocol': PROTOCOL, 'phase': 'feedback', 'attempt': 1}
            save(folder / 'feedback-job.json', job)
            phase = 'feedback'
            if model_identity() != {k: identity[k] for k in ('model', 'digest')}:
                raise ValueError('Local model changed before feedback')
            state['status'] = 'running_feedback'
            save(output / 'report.json', report)
            print(key + ': feedback started', flush=True)
            if not (folder / 'feedback/report.json').exists():
                if (folder / 'feedback').exists():
                    raise ValueError('Interrupted feedback run; no automatic inference replay')
                launch('evals.feedback_pilot_v2', ['--feedback-worker', folder / 'feedback-job.json'], folder, output, phase)
            feedback = read(folder / 'feedback/report.json')
            state.update(feedback_status=feedback['status'], public_accepted=feedback['accepted'],
                         feedback_counts=feedback['counts'], final_candidate_hash=feedback['final_candidate_hash'])
            state['phases'].append(phase_usage(feedback, phase))
            state.update(metrics=aggregate_usage(state['phases']),
                         fresh_model_calls=sum(row['fresh_model_calls'] for row in state['phases']))
            phase = 'grading'
            workspace = folder / 'feedback/workspace'
            if digest(snapshot(workspace)) != feedback['final_candidate_hash']:
                raise ValueError('Feedback candidate changed after worker termination')
            grading = folder / 'grading'
            if not (grading / 'report.json').exists():
                grading.mkdir(exist_ok=True)
                grade = verify(case, workspace, grading)
                grade['resolved'] = grade['passed']
                save(grading / 'report.json', grade)
            grade = read(grading / 'report.json')
            if digest(snapshot(workspace)) != feedback['final_candidate_hash']:
                raise ValueError('Grading mutated the final candidate')
            state.update(status='graded', resolved=grade['resolved'])
            state['input_integrity'] = {name: read(folder / (name + '-input-evidence.json'))['server_input_truncation']
                                        for name in ('initial', 'feedback')}
            check_case(case)
            print(f'{key}: {feedback["status"]}, public={feedback["accepted"]}, resolved={grade["resolved"]}', flush=True)
        except Exception as exc:  # noqa: BLE001 - preserve each first attempt and continue
            state.update(status='infra_error', phase=phase, error_type=type(exc).__name__, error=str(exc))
            print(key + ': ' + phase + ' failed ' + type(exc).__name__, flush=True)
        finally:
            for label, trace in (('initial', folder / 'initial/agent/trace.jsonl'),
                                 ('feedback', folder / 'feedback-trace.jsonl')):
                if trace.exists() and not any(row['phase'] == label for row in state['phases']):
                    state['phases'].append(trace_usage(trace, label))
            state.update(metrics=aggregate_usage(state['phases']),
                         fresh_model_calls=sum(row['fresh_model_calls'] for row in state['phases']))
            report['summary'] = summarize(report['tasks'])
            save(output / 'report.json', report)
    if report.get('status') != 'cancelled':
        report['status'] = 'completed' if all(row.get('status') == 'graded' for row in report['tasks'].values()) else 'completed_with_errors'
    report['summary'] = summarize(report['tasks'])
    final_identity = {**model_identity(), 'sandbox': runner.preflight()}
    save(output / 'identity-after.json', final_identity)
    if final_identity != identity:
        report['status'] = 'identity_changed'
    save(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--output', type=Path)
    modes.add_argument('--feedback-worker', type=Path)
    modes.add_argument('--initial-worker', type=Path)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if args.feedback_worker:
        feedback_worker(inside(args.feedback_worker))
    elif args.initial_worker:
        initial_worker(inside(args.initial_worker))
    else:
        output = inside(args.output)
        if not output.is_relative_to(ROOT / '.tmp'):
            parser.error('Use project .tmp on D:')
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.with_suffix('.lock').open('a+b') as lock:
            lock.seek(0)
            if os.name == 'nt':
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(json.dumps(execute(output, resume=args.resume, prepare_only=args.prepare_only)['summary']))


if __name__ == '__main__':
    main()
