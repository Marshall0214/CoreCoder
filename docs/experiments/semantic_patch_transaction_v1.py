"""Opt-in public semantic gate for final patches, before original-source writes."""
import ast
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from docs.experiments import patch_transaction_v1 as structural
from docs.experiments import runtime_observation_v1 as observer


@dataclass(frozen=True)
class PublicCheck:
    harness: Path
    canonical: Path
    code_sha256: str
    harness_hash: str
    task_id: str


def digest(files):
    return hashlib.sha256(json.dumps({k: hashlib.sha256(v).hexdigest() for k,v in files.items()},
                                     sort_keys=True).encode()).hexdigest()


def validate_check(check):
    code = check.canonical.read_bytes()
    if hashlib.sha256(code).hexdigest() != check.code_sha256:
        raise ValueError('Canonical public check changed')
    files = structural.files(check.harness)
    if files != {'test_admission.py': code}:
        raise ValueError('Public harness must contain only the exact canonical check')
    if observer.public.repair.digest(observer.public.repair.snapshot(check.harness)) != check.harness_hash:
        raise ValueError('Public harness changed')
    owners = [n for n in ast.parse(code).body if isinstance(n, ast.ClassDef) and n.name == 'PublicContract']
    if len(owners) != 1:
        raise ValueError('Expected one PublicContract class')
    tests = [n.name for n in owners[0].body if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')]
    if not tests or len(tests) != len(set(tests)):
        raise ValueError('Expected unique concrete public test methods')
    return len(tests)


def _write(path, data):
    path.write_bytes(data)


def transact(content, workspace, allowed_files, evidence, output, python, imports, check):
    """No public failure writes to original source; caller exclusively owns workspace.

    Public tests are a bounded acceptance gate, not complete correctness, a lock,
    crash-safe multi-file commit, or an OS sandbox. No model calls or private grader.
    """
    workspace, output = Path(workspace).resolve(), Path(output).resolve()
    protected = [workspace, check.harness.resolve()]
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('Output must be separate from source and public harness')
    if check.harness.resolve().is_relative_to(workspace) or workspace.is_relative_to(check.harness.resolve()):
        raise ValueError('Public harness must be separate from source')
    if check.canonical.resolve().is_relative_to(workspace) or check.canonical.resolve().is_relative_to(output):
        raise ValueError('Canonical public check must be outside source and output')
    expected_tests = validate_check(check)
    before = structural.files(workspace)
    output.mkdir(parents=True, exist_ok=False)
    result = {'accepted': False, 'committed': False, 'reason': None, 'changed_files': [],
              'structural': None, 'public_check': None, 'rollback': None,
              'original_before_sha256': digest(before), 'canonical_sha256': check.code_sha256,
              'expected_public_tests': expected_tests}

    def finish(reason):
        result['reason'] = reason
        current = structural.files(workspace)
        result['original_unchanged'] = current == before
        result['original_after_sha256'] = digest(current)
        (output/'transaction.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result

    stage = output/'candidate'
    shutil.copytree(workspace, stage)
    try:
        checked = structural.transact(content, stage, allowed_files, evidence, output/'structural', python, imports)
    except (ValueError, OSError) as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        return finish('structural_error')
    result['structural'] = checked
    if not checked['accepted']:
        return finish(checked['reason'])
    result['changed_files'] = checked['changed_files']
    if not checked['changed_files']:
        return finish('no_changes')
    candidate = structural.files(stage)
    result['candidate_sha256'] = digest(candidate)
    try:
        validate_check(check)
        public, diagnostic = observer.check_public(stage, check.harness, check.harness_hash,
                                                   output/'public', Path(python), check.task_id)
        result['public_check'] = public
        (output/'public-diagnostic.txt').write_text(diagnostic, encoding='utf-8')
        validate_check(check)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        return finish('public_check_error')
    if structural.files(stage) != candidate:
        return finish('candidate_changed')
    if not public['passed'] or public['classification'] != 'passed':
        return finish('public_check_failed')
    if public['tests_run'] != expected_tests:
        return finish('public_test_count_mismatch')
    if structural.files(workspace) != before:
        return finish('source_changed')
    written = []
    try:
        for name in checked['changed_files']:
            written.append(name)
            _write(workspace/name, candidate[name])
        if structural.files(workspace) != candidate:
            raise OSError('Committed source differs from checked candidate')
    except OSError as exc:
        failures = []
        for name in reversed(written):
            try:
                (workspace/name).write_bytes(before[name])
            except OSError as restore:
                failures.append({'path': name, 'error': str(restore)})
        restored = structural.files(workspace) == before
        result.update(error=str(exc), rollback={'restored': restored, 'failures': failures})
        return finish('commit_failed' if restored else 'rollback_failed')
    result.update(accepted=True, committed=True)
    return finish('committed')
