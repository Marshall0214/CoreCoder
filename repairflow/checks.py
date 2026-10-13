"""Same group predicates as the experiment, using the active Python interpreter."""
import os
import shutil
import sys
from pathlib import Path

from docs.experiments import public_feedback_v2 as historical
from evals.process import run_process, test_environment
from evals.runner import changes, digest, snapshot
from repairflow.bundles import read
from sandbox import runner

repair = historical.repair
diagnostic = historical.diagnostic
all_pass = historical.all_pass


def groups(source, harness, package, source_root, logs, names):
    source, harness, logs = Path(source), Path(harness), Path(logs)
    initial = digest(snapshot(source)), digest(snapshot(harness))
    logs.mkdir(parents=True, exist_ok=False)
    outcomes = {}
    policy = (runner.ACTIVE_POLICY.get() or runner.preflight()) if runner.backend() == 'docker' else None
    for name in names:
        record = logs / (name + '.json')
        if policy:
            process = runner.run(source, harness, package, source_root, logs, name,
                                 historical.admission.previous.BOOT, policy,
                                 runner.owner(os.environ.get('CORECODER_SANDBOX_OWNER', str(logs.parent))))
        else:
            process = run_process([sys.executable, '-I', '-B', '-c', historical.admission.previous.BOOT,
                               str((source / source_root).resolve()), str(harness.resolve()), package, name,
                               str(record.resolve())], source, 15, logs / (name + '.stdout.txt'),
                                  logs / (name + '.stderr.txt'), test_environment(source))
        score = read(record) if record.exists() else {}
        passed = (process['returncode'] == 0 and not process['timed_out'] and score.get('tests_run', 0) > 0
                  and score.get('successful') and not any(score.get(k, 0) for k in
                      ('skipped', 'expected_failures', 'unexpected_successes', 'errors', 'failures')))
        outcomes[name] = dict(process, **score, passed=bool(passed))
    if initial != (digest(snapshot(source)), digest(snapshot(harness))):
        raise ValueError('Checks mutated source or test inputs')
    return outcomes


def public_check(source, harness, package, source_root, logs):
    return groups(source, harness, package, source_root, logs, ('Reproduce', 'Preserve'))


def verify(case, workspace, root):
    candidate = snapshot(workspace)
    changed, patch = changes(snapshot(Path(case['before'])), candidate)
    (root / 'patch.diff').write_text(patch, encoding='utf-8')
    violations = sorted(set(changed) - set(case['allowed_files']))
    violations += [name for name in case['allowed_files'] if name not in candidate or (workspace / name).is_symlink()]
    if violations:
        return {'passed': False, 'scope_violations': violations, 'changed_files': changed, 'groups': None}
    grading = root / 'grading'
    shutil.copytree(case['before'], grading)
    for name in changed:
        (grading / name).write_bytes(candidate[name])
    outcomes = groups(grading, case['checks'], case['package'], case['source_root'], root / 'grading-logs', ('Target', 'Controls'))
    return {'passed': all(g['passed'] for g in outcomes.values()), 'scope_violations': [], 'changed_files': changed,
            'groups': outcomes, 'scope': 'hand-authored Target and Controls; not entire upstream suite'}
