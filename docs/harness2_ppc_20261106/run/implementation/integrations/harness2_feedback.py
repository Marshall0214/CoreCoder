"""Optional public-feedback phase for Harness2 rollouts; independent grading stays later."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from integrations import harness2 as bridge
from integrations.harness2_runtime import COMMIT, ROOT, load, workspace


def options(checks, package, rounds=20, timeout=1200, source_root='.'):
    checks = Path(checks).resolve()
    if not checks.is_relative_to(ROOT) or not checks.is_dir() or checks.is_symlink():
        raise ValueError('Use controller-owned public checks inside the workspace')
    if type(rounds) is not int or rounds < 1 or type(timeout) is not int or timeout < 1:
        raise ValueError('Positive feedback rounds and timeout required')
    if not isinstance(package, str) or not package.isidentifier():
        raise ValueError('Require a declared package')
    if (not isinstance(source_root, str) or not source_root or Path(source_root).is_absolute()
            or '..' in Path(source_root).parts or any(c in source_root for c in (':', '\\'))):
        raise ValueError('Require a relative source root')
    files = {}
    for path in sorted(checks.rglob('*')):
        if path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 1024:
            raise ValueError('Links in public checks are forbidden')
        if path.is_file():
            files[path.relative_to(checks).as_posix()] = bridge.sha(path)
    if 'test_admission.py' not in files:
        raise ValueError('Missing public admission checks')
    result = {'checks': str(checks), 'package': package, 'max_feedback_rounds': rounds,
              'timeout': timeout, 'files': files}
    if source_root != '.':
        result['source_root'] = source_root
    return result


def verify_options(config):
    current = options(config['checks'], config['package'], config['max_feedback_rounds'], config['timeout'],
                      config.get('source_root', '.'))
    if current != config:
        raise ValueError('Public feedback configuration or checks changed')


def verify_candidate(job, previous):
    """The Agent's filtered text export is not a deletion patch against the full repo."""
    from evals.runner import changes, digest, snapshot

    source = snapshot(Path(job['source']))
    if digest(source) != job['source_hash']:
        raise ValueError('Baseline source changed')
    baseline = bridge.read(previous / 'agent/baseline-files.json')
    if any(name not in source or hashlib.sha256(source[name]).hexdigest() != value for name, value in baseline.items()):
        raise ValueError('Agent export does not match baseline source')
    report = bridge.read(previous / 'agent/report.json')
    if bridge.sha(previous / 'agent/patch.diff') != report['patch_sha256']:
        raise ValueError('Saved patch changed')
    changed, patch = changes({name: source[name] for name in baseline}, snapshot(previous / 'agent/workspace'))
    if changed != report['changed_files'] or patch != (previous / 'agent/patch.diff').read_bytes().decode('utf-8'):
        raise ValueError('Saved workspace does not reconstruct its patch')
    from evals.swebench_agent import editable
    if any(name not in baseline or not editable(name) for name in changed):
        raise ValueError('Candidate changed undeclared source or tests')
    return changed


def restore_candidate(job, folder):
    """Explicit saved-rollout continuation, with original reports/usage unmodified."""
    previous = workspace(job['reuse_rollout'])
    original = bridge.read(previous / 'job.json')
    for key in ('source_hash', 'public_sha256', 'harness_sha256', 'harness', 'context_enabled'):
        if original.get(key) != job.get(key):
            raise ValueError('Saved candidate does not match this pinned rollout')
    if bridge.sha(previous / 'public.json') != job['public_sha256']:
        raise ValueError('Saved public task changed')
    verify_candidate(job, previous)
    report = bridge.read(previous / 'agent/report.json')
    shutil.copytree(previous / 'agent', folder / 'agent')
    bridge.write(folder / 'reuse.json', {'source_rollout': str(previous), 'fresh_model_calls': 0,
        'historical_model_calls': report['fresh_model_calls'],
        'original_report_sha256': bridge.sha(previous / 'agent/report.json'),
        'copied_report_sha256': bridge.sha(folder / 'agent/report.json'),
        'scope': 'Saved actual output; no regenerated candidate and no historical calls counted as fresh'})


def continue_rollout(path):
    from evals.swebench_agent import RepositoryTools
    from integrations.harness2_context import DEFAULT, POLICY_FILE, policy
    from repairflow import feedback_repair

    job, folder = bridge.read(path), path.parent
    config = job['public_feedback']
    verify_options(config)
    hints = job['harness']
    bridge.validate_harness(hints, job.get('context_enabled', False))
    context = policy(hints[POLICY_FILE]) if job.get('context_enabled') else DEFAULT
    changed = verify_candidate(job, folder)
    candidate = folder / 'candidate-input'
    shutil.copytree(Path(job['source']), candidate)
    for name in changed:
        (candidate / name).write_bytes((folder / 'agent/workspace' / name).read_bytes())
    # These are all existing editable source paths, not an answer-derived file list.
    allowed = RepositoryTools(candidate, folder).allowed
    if job['scripted']:
        raise ValueError('Use injected tests for feedback; no real-model fallback from scripted rollouts')
    result = feedback_repair.run(Path(job['source']), candidate, allowed,
        Path(config['checks']), config['package'], bridge.read(folder / 'public.json'), folder / 'feedback',
        max_feedback_rounds=config['max_feedback_rounds'], timeout=config['timeout'],
        guidance='\n\n'.join(hints[name] for name in bridge.FILES), context_policy=context,
        trace_metadata={key: job[key] for key in ('experiment_id', 'task_id', 'harness_variant')},
        source_root=config.get('source_root', '.'))
    verify_options(config)
    bridge.write(folder / 'execution.json', {'artifact_directory': 'feedback', 'phase': 'public_feedback',
        'status': result['status'], 'public_accepted': result['accepted'],
        'max_feedback_rounds': config['max_feedback_rounds'],
        'feedback_rounds_attempted': result['feedback_rounds_attempted'],
        'initial_candidate_reused': bool(job.get('reuse_rollout')), 'independent_grading_available': False})


def artifact_dir(folder):
    folder = Path(folder)
    job = bridge.read(folder / 'job.json') if (folder / 'job.json').exists() else {}
    if job.get('public_feedback'):
        execution = bridge.read(folder / 'execution.json')
        if execution['artifact_directory'] != 'feedback':
            raise ValueError('Unexpected rollout artifact directory')
        return folder / 'feedback'
    return folder / 'agent'


def summary(folder):
    folder = Path(folder)
    first = bridge.read(folder / 'agent/report.json')
    reused = (folder / 'reuse.json').exists()
    phases = [('candidate', first, not reused)]
    if (folder / 'execution.json').exists():
        phases.append(('feedback', bridge.read(folder / 'feedback/report.json'), True))
    rows = []
    for name, report, fresh in phases:
        counts = [report.get('metrics', {}).get(key) for key in ('prompt_tokens', 'completion_tokens')]
        calls = report.get('fresh_model_calls', 0) if fresh else 0
        tokens = sum(counts) if fresh and all(type(n) is int for n in counts) else 0 if not calls else None
        rows.append({'phase': name, 'fresh_model_calls': calls, 'tokens': tokens, 'reused': not fresh,
                     'trace_id': report.get('observability', {}).get('trace_id')})
    tokens = None if any(row['tokens'] is None for row in rows) else sum(row['tokens'] for row in rows)
    return {'fresh_model_calls': sum(row['fresh_model_calls'] for row in rows), 'actual_tokens': tokens,
            'phases': rows, 'artifact_directory': artifact_dir(folder).name}


def grade(case, folder):
    """Only called by the controller after rollout termination; never returns to a model."""
    from evals.runner import digest, snapshot
    from repairflow.checks import verify

    folder = Path(folder)
    final = artifact_dir(folder)
    report = bridge.read(final / 'report.json')
    if digest(snapshot(final / 'workspace')) != report['final_candidate_hash']:
        raise ValueError('Final feedback workspace changed after termination')
    output = folder / 'grading'
    output.mkdir()
    result = verify(case, final / 'workspace', output)
    result['resolved'] = result['passed']
    bridge.write(output / 'report.json', result)
    return result


def single(output, trial, reuse=False, rounds=20):
    """Exercise the real adapter with frozen adopted guidance; no new strategy search."""
    load()
    from harness2.core import tree

    trial = workspace(trial)
    previous = trial / 'executions/issue-cc-agg1/toolz-join-unmatched/agg1'
    saved = bridge.read(previous / 'job.json')
    case = bridge.read(trial / 'identity/job.json')['case']
    bridge.validate_harness(saved['harness'], saved.get('context_enabled', False))
    output.mkdir(parents=True, exist_ok=False)
    config = options(ROOT / 'repairflow/validation_checks/toolz_join', 'toolz', rounds)
    bridge.write(output / 'identity/job.json', {'kind': 'identity', 'case': case})
    bridge.child(output / 'identity/job.json', 60)
    source = output / 'input'
    shutil.copytree(trial / 'input', source)
    Adapter, _ = bridge.classes(saved.get('context_enabled', False), config)
    adapter = Adapter(output, bridge.read(previous / 'public.json'), source, saved['source_hash'], False)
    if reuse:
        adapter.reuse_rollout = previous
    tree.write_tree(adapter.substrate.surface(), saved['harness'], adapter.base_harness(), stubs=False)
    names = ('integrations/harness2.py', 'integrations/harness2_feedback.py', 'repairflow/feedback_repair.py',
             'repairflow/patch_validator.py', 'integrations/harness2_context.py')
    bridge.write(output / 'protocol.json', {'upstream_commit': COMMIT, 'strategy_search': False,
        'kind': 'Frozen Harness2 adapter execution with public feedback', 'known_development_task': True,
        'reuse_rollout': str(previous) if reuse else None, 'public_feedback': config,
        'harness': saved['harness'], 'harness_sha256': saved['harness_sha256'],
        'source_files': {name: bridge.sha(ROOT / name) for name in names},
        'original_trial_manifest_sha256': bridge.sha(ROOT / 'docs/harness2-autonomous-20261104.json'),
        'independent_grading_after_termination': True})
    folder = adapter.execute(case['task_id'], adapter.base_harness(), 'feedback-validation/toolz-join-unmatched/agg1')
    # The independent case is supplied only to the later grader, never the rollout job.
    bridge.write(output / 'grading/job.json', {'kind': 'grade', 'case': case, 'rollouts': adapter.rollouts})
    bridge.child(output / 'grading/job.json', 180)
    result = {'status': 'completed', 'scope': 'One saved-strategy chain, not new PPC or a repair-rate estimate',
              'execution': bridge.read(folder / 'execution.json'), 'usage': summary(folder),
              'grading': bridge.read(output / 'grading/grading.json'), 'rollout': str(folder)}
    bridge.write(output / 'identity-final/job.json', {'kind': 'identity', 'case': case})
    bridge.child(output / 'identity-final/job.json', 60)
    protocol = bridge.read(output / 'protocol.json')
    if any(bridge.sha(ROOT / name) != value for name, value in protocol['source_files'].items()):
        raise ValueError('Integration code changed during the run')
    bridge.write(output / 'report.json', result)
    print(json.dumps(result), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--from-trial', type=Path, required=True)
    parser.add_argument('--reuse-rollout', action='store_true')
    parser.add_argument('--feedback-rounds', type=int, default=20)
    args = parser.parse_args()
    single(workspace(args.output), args.from_trial, args.reuse_rollout, args.feedback_rounds)


if __name__ == '__main__':
    main()
