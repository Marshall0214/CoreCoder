"""Opt-in mini-SWE-agent comparison on five fixed legacy tasks, using local Ollama."""
import argparse
import hashlib
import inspect
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from evals import local50
from evals.checkpoint_pilot import BASELINE, publish
from evals.mini_swe_adapter import MiniEnvironment, MiniModel, TextOllamaProvider, configure
from evals.runner import changes, digest, snapshot
from evals.runtime import BudgetExceeded, BudgetLLM
from evals.schema import RunConfig
from evals.swebench_agent import AgentTelemetry
from evals.swebench_batch import environment, save
from evals.swebench_mini import ROOT, sha, write
from repairflow.issue_providers import ProviderFailure
from repairflow.telemetry import ObservedEvents

TASKS = ('click-usage-empty', 'toolz-join-unmatched', 'boltons-repeat-equality',
         'toolz-merge-mapping', 'more-reverse-empty-range')
VERSION = '2.4.6'


def run_config(token_budget=30000):
    if type(token_budget) is not int or token_budget not in (30000, 100000):
        raise ValueError('Use the frozen 30k baseline or the 100k budget-only diagnostic')
    return RunConfig(mode='live', model='qwen3.5:27b', base_url='http://127.0.0.1:11434',
                     max_rounds=20, token_budget=token_budget, max_output_tokens=2048, context_tokens=16000,
                     wall_timeout=1200, output_policy='remaining')


def protocol_name(token_budget):
    return 'mini-swe-local50-v1' if token_budget == 30000 else 'mini-swe-local50-budget100k-v1'


def upstream():
    configure(ROOT / '.tmp/mini-swe-state')
    import minisweagent
    import yaml
    from minisweagent.agents.default import DefaultAgent

    if minisweagent.__version__ != VERSION:
        raise ValueError('Require mini-swe-agent==' + VERSION)
    config_path = minisweagent.package_dir / 'config/default.yaml'
    return DefaultAgent, yaml.safe_load(config_path.read_text(encoding='utf-8')), {
        'version': VERSION, 'default_agent_sha256': sha(Path(inspect.getfile(DefaultAgent))),
        'config_sha256': sha(config_path), 'action_protocol': 'upstream text-based Bash',
        'agent_loop_modified': False}


def mini_environment(output, phase):
    env = environment(phase, output)
    env['PYTHONPATH'] = str(ROOT / '.tmp/mini-swe-deps') + os.pathsep + env['PYTHONPATH']
    env.update(MSWEA_GLOBAL_CONFIG_DIR=str(ROOT / '.tmp/mini-swe-state'), MSWEA_SILENT_STARTUP='1')
    return env


def worker(path):
    job, folder = local50.read(path), path.parent
    task, output = local50.read(folder / 'public.json'), folder / 'agent'
    if sha(folder / 'public.json') != job['public_sha256'] or digest(snapshot(Path(job['source']))) != job['source_hash']:
        raise ValueError('Public input or original source changed')
    DefaultAgent, settings, identity = upstream()
    output.mkdir()
    started = time.monotonic()
    source = output / 'seed'
    local50.export(Path(job['source']), source)
    initial = snapshot(source)
    write(output / 'baseline-files.json', {name: hashlib.sha256(data).hexdigest() for name, data in initial.items()})
    config = run_config(job.get('token_budget', 30000))
    report = {'status': 'initializing', 'instance_id': task['instance_id'], 'model': config.model,
              'thinking': False, 'protocol': protocol_name(config.token_budget), 'upstream': identity, 'limits': config.to_dict(),
              'hidden_grading_feedback': False, 'is_agent_result': True,
              'independent_grading': 'after_agent_termination', 'max_edit_attempts': None,
              'edit_limit_note': 'Native Bash edits have no equivalent of the structured six-edit limit'}
    observer = AgentTelemetry(output, {**task, 'source_sha256': job['source_hash'],
                                      'harness_sha256': 'withheld-local50-grading'}, 'ollama', config.model)
    events = ObservedEvents(output / 'trace.jsonl', folder.name, observer)
    llm = BudgetLLM(TextOllamaProvider(config.model, started + 1200), config, events)
    env = agent = None
    try:
        env = MiniEnvironment(source, output, job['sandbox'], events, started + 1200)
        model = MiniModel(llm, settings['model'], output, events)
        agent_config = dict(settings['agent'])
        agent_config.update(step_limit=20, cost_limit=0.0, wall_time_limit_seconds=1200,
                            output_path=output / 'trajectory.json')
        agent_config['instance_template'] += '''
Repository: /workspace. Only edit existing non-test Python source for the Issue.
Original tests can be read and run; do not change them. Temporary reproduction files are allowed
but are excluded from the submitted patch. Private grading files are unavailable.
Available commands include bash, find, grep, sed and python; git and rg are not installed.
PYTHONPATH includes /workspace/src and /workspace. No network or package installation is available.
'''
        agent = DefaultAgent(model, env, **agent_config)
        outcome = agent.run(task['problem_statement'])
        report['status'] = outcome.get('exit_status', 'unknown')
    except (BudgetExceeded, ProviderFailure) as exc:
        report['status'] = 'budget_exceeded' if isinstance(exc, BudgetExceeded) else exc.status
    except Exception as exc:  # noqa: BLE001 - keep artifacts and remove only this container
        report.update(status='agent_error', error_type=type(exc).__name__)
    finally:
        try:
            if env:
                env.export(output / 'workspace-all')
                final = snapshot(output / 'workspace-all')
                report['excluded_new_files'] = sorted(set(final) - set(initial))
                report['deleted_baseline_files'] = sorted(set(initial) - set(final))
                workspace = output / 'workspace'
                workspace.mkdir()
                # Keep modifications to existing non-source files visible to scope checks.
                # Ignore only newly created reproduction helpers, as explicitly configured.
                for name in sorted(set(initial) & set(final)):
                    target = workspace / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(final[name])
                changed, patch = changes(initial, snapshot(workspace))
                report['changed_files'] = changed
                (output / 'patch.diff').write_text(patch, encoding='utf-8', newline='\n')
                report['patch_sha256'] = sha(output / 'patch.diff')
        except Exception as exc:  # noqa: BLE001 - preserve export failure separately from model failure
            report.update(export_error=type(exc).__name__)
        finally:
            if env:
                try:
                    env.close()
                except Exception as exc:  # noqa: BLE001 - retain evidence even when Docker cleanup fails
                    report['cleanup_error'] = type(exc).__name__
        report.update(metrics=llm.metrics(), fresh_model_calls=llm.calls,
                      agent_query_attempts=agent.n_calls if agent else 0,
                      seconds=round(time.monotonic() - started, 3))
        report['observability'] = observer.finish(report)
        write(output / 'report.json', report)


def grade(case, folder):
    report = local50.read(folder / 'agent/report.json')
    if report.get('export_error'):
        raise ValueError('Candidate export failed')
    if report.get('deleted_baseline_files'):
        result = {'resolved': False, 'passed': False, 'groups': None,
                  'scope_violations': report['deleted_baseline_files'], 'reason': 'Baseline file deletion is not permitted'}
        write(folder / 'grading/report.json', result)
        return result
    return local50.grade(case, folder)


def run(output, tasks=TASKS, token_budget=30000):
    import urllib.request

    from sandbox import runner

    config = run_config(token_budget)
    _agent, _settings, upstream_identity = upstream()
    original = local50.read(BASELINE / 'protocol.json')
    if any(sha(ROOT / name) != value for name, value in original['source_files'].items()):
        raise ValueError('Preserve original Agent source for comparison')
    identity = local50.read(BASELINE / 'identity.json')
    policy = runner.preflight()
    models = json.load(urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=10))
    actual = next(row['digest'] for row in models['models'] if row['name'] == identity['model'])
    if actual != identity['digest'] or policy != identity['sandbox']:
        raise ValueError('Keep model digest and grading environment fixed')
    if not tasks or len(tasks) != len(set(tasks)) or not set(tasks) <= set(TASKS):
        raise ValueError('Use the predefined development tasks')
    runner.ACTIVE_POLICY.set(policy)
    os.environ['CORECODER_TEST_BACKEND'] = 'docker'
    output.mkdir(parents=True, exist_ok=False)
    sources = ('evals/mini_swe.py', 'evals/mini_swe_adapter.py')
    write(output / 'protocol.json', {'name': protocol_name(config.token_budget), 'tasks': tasks, 'upstream': upstream_identity,
        'identity': identity, 'original_protocol_sha256': sha(BASELINE / 'protocol.json'),
        'baseline_report_sha256': sha(BASELINE / 'report.json'),
        'sources': {name: sha(ROOT / name) for name in sources},
        'limits': {'requests': 20, 'token_budget': config.token_budget, 'output_tokens': 2048, 'estimated_context': 16000,
                   'deadline_seconds': 1200, 'thinking': False, 'model_attempts_per_task': 1},
        'comparison_scope': 'Whole-system development comparison; prompts/tools/history/edit limits differ',
        'model_interface': 'Upstream supported text actions; native tool calls not used',
        'hidden_feedback': False, 'new_helpers_in_submission': False})
    report = {'status': 'running', 'tasks': {}, 'baseline': {key: local50.read(BASELINE / 'report.json')['tasks'][key]
                                                          for key in tasks}}
    save(output / 'report.json', report)
    cases = {case['task_id']: case for case in local50.read(local50.MANIFEST)['cases']}
    # Reuse independently verified control certificates, never expose their answers to workers.
    for key in tasks:
        case = cases[key]
        for name in ('before', 'after', 'checks'):
            if digest(snapshot(Path(case[name]))) != case[name + '_hash']:
                raise ValueError('Historical fixture changed: ' + key)
        for mode in ('unchanged', 'reference'):
            control = local50.read(BASELINE / 'tasks' / key / ('control-' + mode) / 'summary.json')
            if not control['Controls']['passed'] or control['Target']['passed'] != (mode == 'reference'):
                raise ValueError('Require passing original control certificates: ' + key)
    for key in tasks:
        case, folder = cases[key], output / 'tasks' / key
        folder.mkdir(parents=True)
        public = local50.read(BASELINE / 'tasks' / key / 'public.json')
        write(folder / 'public.json', public)
        write(folder / 'job.json', {'source': case['before'], 'source_hash': case['before_hash'],
                                   'public_sha256': sha(folder / 'public.json'), 'sandbox': policy,
                                   'token_budget': config.token_budget})
        with (folder / 'worker.log').open('wb') as stream:
            process = subprocess.run([sys.executable, '-B', '-m', 'evals.mini_swe', '--worker', folder / 'job.json'],
                cwd=ROOT, env=mini_environment(output, 'agent'), stdout=stream, stderr=subprocess.STDOUT,
                timeout=1350, check=False)
        if process.returncode:
            raise RuntimeError('Worker failed; no automatic model retry: ' + key)
        agent = local50.read(folder / 'agent/report.json')
        result = grade(case, folder)
        counts = [agent['metrics'].get(name) for name in ('prompt_tokens', 'completion_tokens')]
        report['tasks'][key] = {'resolved': result['resolved'], 'grade': result, 'agent_status': agent['status'],
            'fresh_model_calls': agent['fresh_model_calls'], 'changed_files': agent['changed_files'],
            'total_tokens': sum(counts) if all(value is not None for value in counts) else None,
            'trace_id': agent.get('observability', {}).get('trace_id')}
        save(output / 'report.json', report)
        print(key, agent['status'], 'resolved=', result['resolved'], flush=True)
    report.update(status='completed', summary={
        'tasks': len(tasks), 'baseline_resolved': sum(row['resolved'] for row in report['baseline'].values()),
        'mini_resolved': sum(row['resolved'] for row in report['tasks'].values()),
        'mini_nonempty_patches': sum(bool(row['changed_files']) for row in report['tasks'].values()),
        'mini_calls': sum(row['fresh_model_calls'] for row in report['tasks'].values()),
        'mini_tokens_known_sum': sum(row['total_tokens'] or 0 for row in report['tasks'].values())})
    save(output / 'report.json', report)
    report['observability'] = publish(output, report)['status']
    save(output / 'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output', type=Path)
    group.add_argument('--worker', type=Path)
    parser.add_argument('--task', action='append', choices=TASKS)
    parser.add_argument('--token-budget', type=int, choices=(30000, 100000), default=30000,
                        help='100000 selects the budget-only diagnostic; other limits stay fixed')
    args = parser.parse_args()
    path = (args.worker or args.output).resolve()
    if not path.is_relative_to(ROOT / '.tmp') or (os.name == 'nt' and path.drive.lower() != 'd:'):
        parser.error('Use a fresh project .tmp directory on D:')
    if args.worker:
        worker(path)
    else:
        print(json.dumps(run(path, tuple(args.task) if args.task else TASKS, args.token_budget)['summary']))


if __name__ == '__main__':
    main()
