"""Development-only real repository repair, with parent-owned admission and grading."""

import argparse
import ast
import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

from .process import run_process
from .real_admission import DATA, checked_groups, execute, load_cases
from .runner import PROJECT_ROOT, changes, digest, implementation_metadata, snapshot, write_summary
from .runtime import Events
from .schema import RunConfig

VISIBLE = 'python -m unittest discover -s .real-visible -v'


def visible_checks(checks):
    """Publish Controls and helpers only; never copy Target into the worker workspace."""
    tree = ast.parse((checks / 'test_admission.py').read_text(encoding='utf-8'))
    tree.body = [node for node in tree.body if not isinstance(node, ast.ClassDef) or node.name != 'Target']
    if not any(isinstance(node, ast.ClassDef) and node.name == 'Controls' for node in tree.body):
        raise ValueError('Missing public Controls')
    return ast.unparse(tree) + '\n'


def configure_visible_tools(tools, workspace, python):
    for tool in tools:
        if tool.name == 'bash':
            tool.visible_command = VISIBLE
            tool.visible_runner = lambda logs, timeout=tool.test_timeout: execute(
                workspace, workspace / '.real-visible', 'Controls', logs, python, timeout)


def admitted_case(admission, catalog, case_id):
    report = json.loads(admission.read_text(encoding='utf-8'))
    if report['catalog_hash'] != hashlib.sha256(catalog.read_bytes()).hexdigest():
        raise ValueError('Candidate catalog differs from admitted catalog')
    cases = [case for case in load_cases(catalog) if case['case_id'] == case_id]
    rows = [row for row in report['cases'] if row['case_id'] == case_id]
    if len(cases) != 1 or len(rows) != 1 or not rows[0]['admitted']:
        raise ValueError('Task must have one successful admission')
    case, row = cases[0], rows[0]
    checks = DATA / 'checks' / case['test_directory']
    if row['checks_hash'] != digest(snapshot(checks)):
        raise ValueError('Checks differ from admitted checks; rerun admission')
    source_root = admission.parent / case_id
    for label in ('before', 'after'):
        if digest(snapshot(source_root / label)) != row['revisions'][label]['tree_hash']:
            raise ValueError('Source differs from admitted snapshot')
    return case, row, checks, source_root, report['test_environment']


def verify(case, source_root, checks, workspace, original, allowed, root, python, timeout=30):
    after = snapshot(workspace)
    changed, patch = changes(original, after)
    (root / 'patch.diff').write_text(patch, encoding='utf-8')
    violations = sorted(set(changed) - set(allowed))
    violations += [name for name in allowed if name not in after or (workspace / name).is_symlink()]
    if violations:
        return {'passed': False, 'changed_files': changed, 'scope_violations': sorted(set(violations)),
                'target': None, 'regression': None}
    grading = root / 'grading'
    shutil.copytree(source_root / 'before', grading)
    for name in allowed:
        (grading / name).write_bytes(after[name])
    groups = checked_groups(grading, checks, root / 'grading-logs', python, timeout)
    return {'passed': all(group['passed'] for group in groups.values()), 'changed_files': changed,
            'scope_violations': [], 'target': groups['Target'], 'regression': groups['Controls'],
            'regression_scope': 'public Controls only; not the full upstream suite'}


def run_real(case, row, checks, source_root, environment, config, output, workflow='agent-loop',
             symbol_prompt_policy='baseline', symbol_context_policy='base'):
    if symbol_context_policy not in {'base', 'linked'} or (symbol_context_policy == 'linked' and workflow != 'symbol-patch'):
        raise ValueError('Linked context requires the single symbol patch workflow')
    if symbol_prompt_policy not in {'baseline', 'behavior-check'} or (symbol_prompt_policy != 'baseline'
                                                                     and workflow != 'symbol-patch'):
        raise ValueError('Behavior check requires the symbol patch workflow')
    if workflow not in {'agent-loop', 'symbol-patch', 'symbol-feedback'} or (workflow != 'agent-loop' and config.mode != 'live'):
        raise ValueError('Symbol patch workflow requires live mode; unknown workflows are rejected')
    if workflow == 'symbol-feedback' and case['case_id'] != 'click-flag-envvar':
        raise ValueError('Public symbol feedback checks currently support click-flag-envvar only')
    if workflow != 'agent-loop' and (config.search_backend != 'off' or config.search_history != 'full'
                                      or config.context_policy != 'none' or config.prompt_policy != 'baseline'):
        raise ValueError('Symbol patch is a separate protocol; Agent policies must use defaults')
    if config.mode not in {'unchanged', 'reference', 'scripted', 'live'}:
        raise ValueError('Real development tasks currently support unchanged/reference/scripted/live only')
    if output.resolve().is_relative_to(source_root.resolve()) or output.resolve().is_relative_to(checks.resolve()):
        raise ValueError('Output must stay outside admitted source and checks')
    root = output.resolve() / (case['case_id'] + '-' + uuid.uuid4().hex[:10])
    root.mkdir(parents=True, exist_ok=False)
    events = Events(root / 'trace.jsonl', root.name)
    report = {'run_id': root.name, 'task_id': case['case_id'], 'source': 'real-upstream', 'mode': config.mode,
              'evaluation_protocol': {'symbol-patch': ('symbol-linked-patch-development-v1'
                                                       if symbol_context_policy == 'linked' else 'symbol-patch-development-v1'),
                                      'symbol-feedback': 'symbol-feedback-development-v1',
                                      'agent-loop': 'real-agent-loop-development-v1'}[workflow], 'workflow': workflow,
              'benchmark_eligible': False,
              'symbol_prompt_policy': symbol_prompt_policy,
              'symbol_context_policy': symbol_context_policy,
              'accepted': False, 'status': 'infrastructure_error', 'config': config.to_dict(),
              'metrics': None, 'verification': None, 'artifacts': str(root),
              'provenance': case, 'admission_checks_hash': row['checks_hash'], 'test_environment': environment,
              'implementation': implementation_metadata()}
    started = time.perf_counter()
    events.emit('task_started', task_id=case['case_id'], mode=config.mode)
    try:
        python = Path(environment['executable'])
        # Ensure a pinned snapshot plus its recorded interpreter still reproduces the admitted behavior.
        baseline = checked_groups(source_root / 'before', checks, root / 'preflight', python, config.test_timeout)
        if not (baseline['Controls']['passed'] and baseline['Target']['assertion_failure']
                and not baseline['Target']['passed'] and not baseline['Target']['execution_error']):
            raise ValueError('Original admission behavior no longer reproduces')
        workspace = root / 'workspace'
        shutil.copytree(source_root / 'before', workspace)
        public = workspace / '.real-visible'
        public.mkdir()
        (public / 'test_admission.py').write_text(visible_checks(checks), encoding='utf-8')
        original = snapshot(workspace)
        # Give the entire existing package as the write scope, not the upstream answer locations.
        allowed = sorted(name for name in original if name.startswith('src/click/') and name.endswith('.py'))
        report.update(fixture_hash=digest(original), allowed_files=allowed,
                      visible_checks_hash=digest(snapshot(public)), worker_seconds=0.0)
        if config.mode == 'reference':
            for name in case['changed_source_files']:
                (workspace / name).write_bytes((source_root / 'after' / name).read_bytes())
            worker = {'status': 'completed', 'metrics': None}
        elif config.mode == 'unchanged':
            worker = {'status': 'completed', 'metrics': None}
        else:
            job = {'run_id': root.name, 'workspace': str(workspace), 'description': case['public_problem'],
                   'workflow': workflow,
                   'symbol_prompt_policy': symbol_prompt_policy,
                   'symbol_context_policy': symbol_context_policy,
                   'allowed_files': allowed, 'config': config.to_dict(), 'visible_command': VISIBLE,
                   'real_visible_python': str(python)}
            if config.mode == 'scripted':
                job['oracle_edits'] = [{'file': name,
                                        'old': (source_root / 'before' / name).read_text(encoding='utf-8'),
                                        'new': (source_root / 'after' / name).read_text(encoding='utf-8')}
                                       for name in case['changed_source_files']]
            job_path = root / 'job.json'
            job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
            env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT), PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
                       PYTHONIOENCODING='utf-8')
            result = run_process([sys.executable, '-m', 'evals.worker', str(job_path)], workspace,
                                 config.wall_timeout, root / 'worker.stdout.txt', root / 'worker.stderr.txt', env)
            report['worker_seconds'] = result['seconds']
            result_path = root / 'worker-result.json'
            if result['timed_out']:
                worker = {'status': 'timeout', 'metrics': None}
            elif result['returncode'] != 0 or not result_path.exists():
                worker = {'status': 'agent_error', 'metrics': None}
            else:
                worker = json.loads(result_path.read_text(encoding='utf-8'))
        report['worker'], report['metrics'] = worker, worker.get('metrics')
        if digest(snapshot(checks)) != row['checks_hash']:
            raise ValueError('Parent-owned checks changed during repair')
        for label in ('before', 'after'):
            if digest(snapshot(source_root / label)) != row['revisions'][label]['tree_hash']:
                raise ValueError('Admitted snapshots changed during repair')
        verification = verify(case, source_root, checks, workspace, original, allowed, root, python, config.test_timeout)
        report['verification'] = verification
        report['accepted'] = worker['status'] == 'completed' and verification['passed']
        report['status'] = 'passed' if report['accepted'] else (
            'failed_verification' if worker['status'] == 'completed' else worker['status'])
    except KeyboardInterrupt:
        report['status'] = 'cancelled'
    except Exception as exc:  # noqa: BLE001 - preserve failed runs
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        report['seconds'] = round(time.perf_counter() - started, 4)
        events.emit('task_finished', status=report['status'], accepted=report['accepted'])
        report = events.clean(report)
        (root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, default=DATA / 'crossfile-candidates.json')
    parser.add_argument('--task', default='click-flag-envvar')
    parser.add_argument('--mode', choices=('unchanged', 'reference', 'scripted', 'live'), default='unchanged')
    parser.add_argument('--workflow', choices=('agent-loop', 'symbol-patch', 'symbol-feedback'), default='agent-loop')
    parser.add_argument('--symbol-prompt-policy', choices=('baseline', 'behavior-check'), default='baseline')
    parser.add_argument('--symbol-context-policy', choices=('base', 'linked'), default='base')
    parser.add_argument('--output', type=Path, default=Path('.tmp/real-defects/repair'))
    parser.add_argument('--model', default='qwen3.5:27b')
    parser.add_argument('--base-url', default='http://localhost:11434/v1')
    parser.add_argument('--search-backend', choices=('off', 'none', 'keyword'), default='off')
    parser.add_argument('--search-history', choices=('full', 'deduplicate'), default='full')
    parser.add_argument('--search-max-chars', type=int, default=6000)
    parser.add_argument('--reasoning-effort', default='none')
    parser.add_argument('--evidence-top-k', type=int, default=5)
    parser.add_argument('--evidence-dependency-depth', type=int)
    for flag, default in (('max-rounds', 12), ('token-budget', 30000), ('max-output-tokens', 2048),
                          ('context-tokens', 16000), ('wall-timeout', 180), ('test-timeout', 15)):
        parser.add_argument('--' + flag, type=int, default=default)
    args = parser.parse_args()
    case, row, checks, source, environment = admitted_case(args.admission.resolve(), args.catalog, args.task)
    config = RunConfig(mode=args.mode, model=args.model, base_url=args.base_url,
                       search_backend=args.search_backend, search_history=args.search_history,
                       search_max_chars=args.search_max_chars,
                       evidence_top_k=args.evidence_top_k,
                       evidence_dependency_depth=(args.evidence_dependency_depth if args.evidence_dependency_depth is not None
                                                  else (2 if args.workflow == 'agent-loop' else 1)),
                       reasoning_effort=args.reasoning_effort,
                       **{name: getattr(args, name) for name in ('max_rounds', 'token_budget', 'max_output_tokens',
                                                               'context_tokens', 'wall_timeout', 'test_timeout')})
    if config.mode == 'live':
        from corecoder.config import _load_dotenv

        _load_dotenv()
    report = run_real(case, row, checks, source, environment, config, args.output, workflow=args.workflow,
                      symbol_prompt_policy=args.symbol_prompt_policy, symbol_context_policy=args.symbol_context_policy)
    print(f"{case['case_id']}: {report['status']}")
    print(write_summary([report], args.output.resolve()))
    return 0 if report['accepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
