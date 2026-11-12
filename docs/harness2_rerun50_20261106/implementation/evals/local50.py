"""Check the current repository Agent on the existing 50 small defect fixtures."""
import argparse
import difflib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from collections import Counter
from pathlib import Path

from evals.runner import changes, digest, snapshot
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.schema import RunConfig
from evals.swebench_agent import AgentTelemetry, RepositoryTools, explore, extract_text
from evals.swebench_batch import environment, save
from evals.swebench_mini import ROOT, sha, write
from repairflow.issue_providers import OllamaProvider, ProviderFailure, ScriptedProvider
from repairflow.telemetry import ObservedEvents

MANIFEST = ROOT / 'docs/repair50_evidence/inputs/manifest.json'
CODE = ('evals/local50.py', 'evals/swebench_agent.py', 'evals/runtime.py', 'evals/schema.py',
        'evals/swebench_batch.py', 'repairflow/issue_providers.py', 'repairflow/issue_tools.py',
        'repairflow/telemetry.py', 'repairflow/checks.py', 'sandbox/runner.py', 'deploy/langfuse/local50.py')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def export(source, output):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w') as archive:
        for path in sorted(source.rglob('*')):
            if path.is_file() and not path.is_symlink() and not any(
                    part.startswith('.') or part == '__pycache__' for part in path.relative_to(source).parts):
                archive.add(path, arcname=path.relative_to(source).as_posix(), recursive=False)
    return extract_text(data.getvalue(), output)


def worker(job_path):
    job, output = read(job_path), job_path.parent / 'agent'
    task = read(output.parent / 'public.json')
    if sha(output.parent / 'public.json') != job['public_sha256'] or digest(snapshot(Path(job['source']))) != job['source_hash']:
        raise ValueError('Public task or baseline source changed')
    output.mkdir()
    started = time.monotonic()
    config = RunConfig(mode='live', model='qwen3.5:27b', base_url='http://127.0.0.1:11434',
                       max_rounds=20, token_budget=30000, max_output_tokens=2048, context_tokens=16000,
                       wall_timeout=1200, output_policy='remaining')
    report = {'status': 'initializing', 'instance_id': task['instance_id'], 'model': config.model,
              'thinking': False, 'protocol': 'local50-repository-agent-v1', 'limits': config.to_dict(),
              'hidden_grading_feedback': False, 'is_agent_result': True, 'official_grading': 'not_applicable',
              'independent_grading': 'after_agent_termination', 'max_edit_attempts': 6}
    observer = llm = None
    try:
        report['export'] = export(Path(job['source']), output / 'workspace')
        tools = RepositoryTools(output / 'workspace', output)
        before = snapshot(tools.workspace)
        write(output / 'baseline-files.json', {name: hashlib.sha256(value).hexdigest() for name, value in before.items()})
        observer = AgentTelemetry(output, {**task, 'source_sha256': job['source_hash'],
                                          'harness_sha256': 'withheld-local50-grading'}, 'ollama', config.model)
        events = ObservedEvents(output / 'trace.jsonl', output.parent.name, observer)
        llm = BudgetLLM(OllamaProvider(config.model, started + 1200), config, events)
        report['status'] = explore(llm, tools, task, output, events)
    except (BudgetExceeded, ProviderFailure) as exc:
        report['status'] = 'budget_exceeded' if isinstance(exc, BudgetExceeded) else exc.status
    finally:
        report.update(seconds=round(time.monotonic() - started, 3), metrics=llm.metrics() if llm else {},
                      fresh_model_calls=llm.calls if llm else 0)
        if 'before' in locals():
            changed, patch = changes(before, snapshot(tools.workspace))
            report['changed_files'] = changed
            (output / 'patch.diff').write_text(patch, encoding='utf-8', newline='\n')
            report['patch_sha256'] = sha(output / 'patch.diff')
        if observer:
            report['observability'] = observer.finish(report)
        write(output / 'report.json', report)


def initialize(output):
    manifest = read(MANIFEST)
    cases = manifest['cases']
    if len(cases) != 50 or len({case['task_id'] for case in cases}) != 50:
        raise ValueError('Require the original 50 distinct tasks')
    for case in cases:
        for key in ('before', 'after', 'checks'):
            if digest(snapshot(Path(case[key]))) != case[key + '_hash']:
                raise ValueError('Historical fixture changed: ' + case['task_id'] + '/' + key)
    output.mkdir(parents=True, exist_ok=False)
    protocol = {'name': 'local50-current-agent-chain-v1', 'task_ids': [case['task_id'] for case in cases],
                'manifest_sha256': sha(MANIFEST), 'source_files': {name: sha(ROOT / name) for name in CODE},
                'model': 'qwen3.5:27b', 'thinking': False, 'max_steps': 20, 'token_budget': 30000,
                'max_edits': 6, 'max_output_tokens': 2048, 'context_tokens': 16000, 'deadline_seconds': 1200,
                'repo_counts': dict(Counter(case['repo'] for case in cases)),
                'grading': 'Existing hand-authored Target + Controls in small Docker sandbox',
                'not_comparable_to_historical_94_percent': True, 'official_swebench_result': False,
                'public_or_hidden_test_feedback_to_agent': False, 'automatic_model_retry': False}
    write(output / 'protocol.json', protocol)
    write(output / 'report.json', {'status': 'prepared', 'protocol_sha256': sha(output / 'protocol.json'), 'tasks': {}})
    return protocol


def summarize(tasks):
    graded = [row for row in tasks.values() if row.get('status') == 'graded']
    agents = [row for row in tasks.values() if 'fresh_model_calls' in row]
    return {'scheduled': 50, 'controls_passed': sum(row.get('controls_passed', False) for row in tasks.values()),
            'graded': len(graded), 'resolved': sum(row['resolved'] for row in graded),
            'agent_attempts': len(agents), 'nonempty_patches': sum(row.get('nonempty_patch', False) for row in agents),
            'fresh_model_calls': sum(row['fresh_model_calls'] for row in agents),
            'actual_tokens_known_sum': sum(row.get('total_tokens') or 0 for row in agents),
            'unknown_usage_tasks': sum(row.get('total_tokens') is None for row in agents),
            'stop_reasons': dict(Counter(row['agent_status'] for row in agents)),
            'infra_errors': sum(row.get('status') == 'infra_error' for row in tasks.values())}


def fixture_controls(case, folder):
    from repairflow.checks import groups

    result = {}
    for mode, source in (('unchanged', Path(case['before'])), ('reference', folder / 'reference-source')):
        if mode == 'reference' and not source.exists():
            shutil.copytree(case['before'], source, ignore=shutil.ignore_patterns('__pycache__', '.git'))
            for name in case['allowed_files']:
                (source / name).write_bytes((Path(case['after']) / name).read_bytes())
        logs = folder / ('control-' + mode)
        if (logs / 'summary.json').exists():
            result[mode] = read(logs / 'summary.json')
        else:
            result[mode] = groups(source, case['checks'], case['package'], case['source_root'], logs,
                                  ('Target', 'Controls'))
            write(logs / 'summary.json', result[mode])
    if (result['unchanged']['Target']['passed'] or not result['unchanged']['Controls']['passed']
            or not all(row['passed'] for row in result['reference'].values())):
        raise ValueError('Fixture control pair failed')
    return result


def grade(case, folder):
    from repairflow.checks import verify

    agent = folder / 'agent'
    report = read(agent / 'report.json')
    workspace = agent / 'workspace'
    initial = read(agent / 'baseline-files.json')
    current = snapshot(workspace)
    changed = sorted(set(initial) | set(current))
    changed = [name for name in changed if initial.get(name) !=
               (hashlib.sha256(current[name]).hexdigest() if name in current else None)]
    violations = sorted(set(changed) - set(case['allowed_files']))
    if changed != report['changed_files'] or sha(agent / 'patch.diff') != report['patch_sha256']:
        raise ValueError('Agent candidate changed after termination')
    if violations:
        result = {'resolved': False, 'passed': False, 'scope_violations': violations, 'groups': None}
        write(folder / 'grading/report.json', result)
        return result
    candidate = folder / 'candidate-source'
    shutil.copytree(case['before'], candidate, ignore=shutil.ignore_patterns('__pycache__', '.git'))
    for name in changed:
        (candidate / name).write_bytes(current[name])
    logs = folder / 'grading'
    logs.mkdir()
    try:
        result = verify(case, candidate, logs)
        result['resolved'] = result['passed']
    except Exception as exc:
        from sandbox.runner import SandboxError

        # Environment admission passed on both baselines. Keep candidate execution
        # failures distinct from container creation/control failures, never a success.
        statuses = {'sandbox_invalid_result', 'sandbox_timeout', 'sandbox_oom', 'sandbox_output_limit'}
        if not isinstance(exc, SandboxError) or exc.status not in statuses:
            raise
        result = {'resolved': False, 'passed': False, 'scope_violations': [], 'groups': None,
                  'candidate_execution_failure': exc.status,
                  'classification': 'Candidate could not produce trustworthy test counts after successful controls'}
    write(logs / 'report.json', result)
    return result


def scripted_smoke(case, folder):
    """Known reference actions validate editing/grade plumbing, never model quality."""
    folder.mkdir(parents=True)
    output = folder / 'agent'
    output.mkdir()
    export(Path(case['before']), output / 'workspace')
    tools = RepositoryTools(output / 'workspace', output)
    initial = snapshot(tools.workspace)
    responses = []
    for name in case['allowed_files']:
        before = initial[name].decode('utf-8')
        after = (Path(case['after']) / name).read_text(encoding='utf-8')
        if before == after:
            continue
        groups = list(difflib.SequenceMatcher(None, before.splitlines(keepends=True),
                                             after.splitlines(keepends=True)).get_grouped_opcodes(3))
        if len(groups) != 1:
            raise ValueError('Smoke fixture requires one reference hunk per file')
        group = groups[0]
        lines, newlines = before.splitlines(keepends=True), after.splitlines(keepends=True)
        old = ''.join(lines[group[0][1]:group[-1][2]])
        new = ''.join(newlines[group[0][3]:group[-1][4]])
        offset = len(''.join(lines[:group[0][1]]))
        if len(old) > 6000 or before.count(old) != 1:
            raise ValueError('Smoke fixture needs a readable unique anchor')
        responses.extend([json.dumps({'action': 'read_file', 'arguments': {'path': name, 'offset': offset}}),
                          json.dumps({'action': 'apply_patch', 'arguments': {'edits': [
                              {'file': name, 'old': old, 'new': new}]}})])
    responses.append(json.dumps({'action': 'finish', 'arguments': {}}))
    write(output / 'responses.json', responses)
    events = Events(output / 'trace.jsonl', 'scripted-engineering-smoke')
    status = explore(ScriptedProvider(output / 'responses.json'), tools,
                     {'problem_statement': case['description']}, output, events)
    changed, patch = changes(initial, snapshot(tools.workspace))
    (output / 'patch.diff').write_text(patch, encoding='utf-8', newline='\n')
    write(output / 'baseline-files.json', {name: hashlib.sha256(value).hexdigest() for name, value in initial.items()})
    write(output / 'report.json', {'status': status, 'changed_files': changed, 'patch_sha256': sha(output / 'patch.diff'),
                                  'fresh_model_calls': 0, 'reference_derived_scripted_actions': True})
    result = grade(case, folder)
    if status != 'agent_finished' or not changed or not result['resolved']:
        raise ValueError('Scripted end-to-end edit and grading smoke failed')
    write(folder / 'smoke.json', {'passed': True, 'fresh_model_calls': 0, 'changed_files': changed,
                                'is_model_performance': False, 'resolved': True})


def execute(output, resume=False):
    import urllib.request

    from sandbox import runner

    protocol = read(output / 'protocol.json') if resume else initialize(output)
    if sha(MANIFEST) != protocol['manifest_sha256'] or any(
            sha(ROOT / name) != value for name, value in protocol['source_files'].items()):
        raise ValueError('Frozen experiment implementation changed')
    policy = runner.preflight()
    os.environ['CORECODER_TEST_BACKEND'] = 'docker'
    runner.ACTIVE_POLICY.set(policy)
    model = json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=10))
    digest_value = next(row['digest'] for row in model['models'] if row['name'] == protocol['model'])
    identity = {'model': protocol['model'], 'digest': digest_value, 'sandbox': policy}
    if (output / 'identity.json').exists() and read(output / 'identity.json') != identity:
        raise ValueError('Model or sandbox image changed')
    write(output / 'identity.json', identity)
    report = read(output / 'report.json')
    cases = read(MANIFEST)['cases']
    # Validate all environments first. Reference answers remain in controller-only
    # smoke/control directories and never enter the live worker's source or request.
    for number, case in enumerate(cases, 1):
        folder = output / 'tasks' / case['task_id']
        folder.mkdir(parents=True, exist_ok=True)
        state = report['tasks'].setdefault(case['task_id'], {'status': 'preparing'})
        if not state.get('controls_passed'):
            report.update(status='preflight', current_task=case['task_id'], current_index=number)
            save(output / 'report.json', report)
            try:
                fixture_controls(case, folder)
            except Exception as exc:
                report.update(status='preflight_failed', error_type=type(exc).__name__)
                state.update(status='infra_error', phase='controls', error_type=type(exc).__name__)
                report['summary'] = summarize(report['tasks'])
                save(output / 'report.json', report)
                raise
            state['controls_passed'] = True
            report['summary'] = summarize(report['tasks'])
            save(output / 'report.json', report)
            print(f'preflight [{number}/50] {case["task_id"]}: passed', flush=True)
    smoke = output / 'scripted-smoke'
    if not (smoke / 'smoke.json').exists():
        case = next(case for case in cases if case['task_id'] == 'toolz-join-unmatched')
        scripted_smoke(case, smoke)
    report['scripted_edit_and_grade_smoke'] = read(smoke / 'smoke.json')
    save(output / 'report.json', report)
    for number, case in enumerate(cases, 1):
        key = case['task_id']
        state = report['tasks'].setdefault(key, {'status': 'preparing'})
        if state['status'] in {'graded', 'infra_error', 'interrupted_agent'}:
            continue
        folder = output / 'tasks' / key
        folder.mkdir(parents=True, exist_ok=True)
        report.update(status='running', current_task=key, current_index=number)
        save(output / 'report.json', report)
        phase = 'controls'
        try:
            fixture_controls(case, folder)
            state['controls_passed'] = True
            task = {'instance_id': key, 'repo': case['repo'], 'base_commit': 'source-sha256:' + case['before_hash'],
                    'problem_statement': case['description']}
            write(folder / 'public.json', task)
            job = {'source': case['before'], 'source_hash': case['before_hash'],
                   'public_sha256': sha(folder / 'public.json')}
            write(folder / 'job.json', job)
            phase = 'agent'
            if (folder / 'agent').exists() and not (folder / 'agent/report.json').exists():
                state['status'] = 'interrupted_agent'
                continue
            if not (folder / 'agent/report.json').exists():
                with (folder / 'agent.log').open('ab') as stream:
                    process = subprocess.run([sys.executable, '-B', '-m', 'evals.local50', '--worker', folder / 'job.json'],
                        cwd=ROOT, env=environment('agent', output), stdout=stream, stderr=subprocess.STDOUT,
                        timeout=1350, check=False)
                if process.returncode:
                    raise RuntimeError('Agent process failed')
            agent = read(folder / 'agent/report.json')
            counts = [agent['metrics'].get(name) for name in ('prompt_tokens', 'completion_tokens')]
            state.update(agent_status=agent['status'], fresh_model_calls=agent['fresh_model_calls'],
                         nonempty_patch=bool(agent['changed_files']),
                         total_tokens=sum(counts) if all(value is not None for value in counts) else None,
                         trace_id=agent.get('observability', {}).get('trace_id'))
            phase = 'grading'
            result = grade(case, folder)
            state.update(status='graded', resolved=result['resolved'], grade=result)
            print(f'[{number}/50] {key}: {agent["status"]}, resolved={result["resolved"]}', flush=True)
        except Exception as exc:  # noqa: BLE001 - retain task-level failures and continue
            state.update(status='infra_error', phase=phase, error_type=type(exc).__name__)
            print(f'[{number}/50] {key}: {phase} error {type(exc).__name__}', flush=True)
        finally:
            report['summary'] = summarize(report['tasks'])
            save(output / 'report.json', report)
    report['status'] = 'completed' if all(row['status'] == 'graded' for row in report['tasks'].values()) else 'completed_with_errors'
    report['summary'] = summarize(report['tasks'])
    save(output / 'report.json', report)
    with (output / 'publish.log').open('ab') as stream:
        process = subprocess.run([sys.executable, '-B', '-m', 'deploy.langfuse.local50', '--batch', output],
            cwd=ROOT, env=environment('publish', output), stdout=stream, stderr=subprocess.STDOUT,
            timeout=300, check=False)
    report['publication'] = 'completed' if process.returncode == 0 else 'failed_see_publish_log'
    save(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path)
    group.add_argument('--worker', type=Path)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    output = args.worker.resolve().parent if args.worker else args.output.resolve()
    if not output.is_relative_to(ROOT / '.tmp') or (os.name == 'nt' and output.drive.lower() != 'd:'):
        parser.error('Use project .tmp on D:')
    if args.worker:
        worker(args.worker.resolve())
    else:
        if output.exists() and not args.resume:
            parser.error('Fresh output required, or --resume existing batch')
        if not args.resume:
            initialize(output)
        with (output / 'batch.lock').open('a+b') as lock:
            lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(json.dumps(execute(output, resume=True)['summary']))


if __name__ == '__main__':
    main()
