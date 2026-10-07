"""Frozen hand-authored public checks, offline certificates and a bounded feedback adapter."""

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

from docs.experiments import symbol_directed_repair_v1 as comparison
from evals.process import run_process, test_environment
from evals.real_admission import execute
from evals.runner import changes
from evals.symbol_context import apply_symbol_patch

repair = comparison.repair
ROOT = comparison.ROOT
TARGETS = ('click-usage-empty', 'itsdangerous-none-salt')
CHECKS = dict(zip(TARGETS, ('usage_empty.py', 'none_salt.py')))
CHECK_ROOT = Path(__file__).with_name('public_checks_v1')


def valid_failure(outcome):
    return (outcome['assertion_failure'] and not outcome['passed'] and not outcome['execution_error']
            and not outcome['timed_out'] and outcome['tests_run'] > 0)


def registry(cases):
    """Exact public-description spans document every hand-authored scenario's source."""
    phrases = {
        TARGETS[0]: [('test_empty_usage_wide', 'when args is empty, without a trailing separator space or extra blank line'),
                     ('test_empty_usage_narrow_custom_prefix', 'Preserve custom prefixes'),
                     ('test_nonempty_arguments_and_custom_prefix', 'normal nonempty argument rendering'),
                     ('test_command_empty_and_none_metavar', 'Commands with no parameters and empty or None options_metavar')],
        TARGETS[1]: [('test_signer_none_uses_signer_default', 'Signer salt=None must match its default'),
                     ('test_serializer_none_matches_explicit_signer', 'Serializer salt=None signatures must match explicit itsdangerous.Signer salt'),
                     ('test_serializer_none_round_trip', 'Signed values must round-trip'),
                     ('test_explicit_string_and_bytes_salts', 'Preserve explicit string and bytes salts'),
                     ('test_omitted_serializer_salt_preserved', 'the Serializer default salt'),
                     ('test_wrong_salt_rejected', 'wrong-salt rejection'),
                     ('test_tampered_value_rejected', 'tamper detection')]}
    rows = {}
    for case in cases:
        name = case['task_id']
        if name not in TARGETS:
            continue
        code = CHECK_ROOT / CHECKS[name]
        clauses = []
        for method, text in phrases[name]:
            start = case['description'].index(text)
            clauses.append({'test': method, 'text': text, 'span': [start, start + len(text)]})
        rows[name] = {'code_path': code.relative_to(ROOT).as_posix(), 'code_sha256': repair.audit.sha(code),
                      'description_sha256': hashlib.sha256(case['description'].encode()).hexdigest(), 'clauses': clauses,
                      'provenance': 'hand-authored public development checks; not hidden scoring or general test generation',
                      'developer_choices': 'demo program/prefix/widths, payload/key/salts; Usage and omitted salt defaults from original API'}
    if set(rows) != set(TARGETS):
        raise ValueError('Expected both public descriptions')
    return rows


def freeze_harness(name, root, record):
    code = CHECK_ROOT / CHECKS[name]
    if repair.audit.sha(code) != record['code_sha256']:
        raise ValueError('Public check implementation changed')
    root.mkdir(parents=True, exist_ok=False)
    (root / 'test_admission.py').write_bytes(code.read_bytes())
    return repair.digest(repair.snapshot(root))


def check_public(workspace, harness, expected_hash, root, python, name):
    if repair.digest(repair.snapshot(harness)) != expected_hash:
        raise ValueError('Public harness changed')
    root.mkdir(parents=True, exist_ok=False)
    source = root / 'source'
    shutil.copytree(workspace, source)
    before = repair.digest(repair.snapshot(source))
    logs = root / 'logs'
    if name.startswith('itsdangerous-'):
        logs.mkdir()
        outcome = run_process([str(python), '-I', '-B', '-c', comparison.second.admission.BOOT,
                               str((source / 'src').resolve()), str(harness.resolve()), 'PublicContract'],
                              source, 15, logs / 'PublicContract.stdout.txt', logs / 'PublicContract.stderr.txt',
                              test_environment(source))
        text = (logs / 'PublicContract.stderr.txt').read_text(encoding='utf-8', errors='replace')
        count = re.search(r'Ran (\d+) tests?', text)
        outcome.update(tests_run=int(count.group(1)) if count else 0,
                       assertion_failure=bool(re.search(r'^FAIL: ', text, re.MULTILINE)),
                       execution_error=bool(re.search(r'^ERROR: ', text, re.MULTILINE)),
                       stderr='PublicContract.stderr.txt', stdout='PublicContract.stdout.txt')
        outcome['passed'] = outcome['returncode'] == 0 and not outcome['timed_out'] and outcome['tests_run'] > 0
    else:
        outcome = execute(source, harness, 'PublicContract', logs, python, 15)
    if (repair.digest(repair.snapshot(source)) != before
            or repair.digest(repair.snapshot(harness)) != expected_hash):
        raise ValueError('Public execution mutated source or checks')
    output = (logs / outcome['stderr']).read_text(encoding='utf-8', errors='replace')
    output = output.replace(str(source), '<PUBLIC_WORKSPACE>').replace(str(harness), '<PUBLIC_CHECKS>')[-6000:]
    return outcome, output


def apply_witness(case, workspace):
    """Manually constructed positive examples, never included in model input."""
    if case['task_id'] == TARGETS[0]:
        name = 'src/click/formatting.py'
        old = '        usage_prefix = f"{prefix:>{self.current_indent}}{prog} "'
        new = ('        if not args:\n            self.write(f"{prefix:>{self.current_indent}}{prog}\\n")\n'
               '            return\n\n' + old)
    elif case['task_id'] == TARGETS[1]:
        name = 'src/itsdangerous/signer.py'
        old = '        self.salt: bytes = want_bytes(salt)'
        new = '        if salt is None:\n            salt = b"itsdangerous.Signer"\n' + old
    else:
        raise ValueError('No positive example for task')
    data = (workspace / name).read_bytes()
    # A small exact cited snippet is sufficient; source version is still the full-file hash.
    lines = data.decode().splitlines(keepends=True)
    position = next(i for i, line in enumerate(lines, 1) if line.rstrip('\r\n') == old)
    row = {'path': name, 'start_line': position, 'end_line': position,
           'content': lines[position - 1], 'content_hash': hashlib.sha256(data).hexdigest()}
    apply_symbol_patch(json.dumps({'edits': [{'file': name, 'old': old, 'new': new}]}), workspace, case['allowed_files'], [row])


def audit(output):
    """No model calls and no reading reference patches or hidden checks to author expectations."""
    cases, grading = comparison.prepare(output)
    selected = [(c, g) for c, g in zip(cases, grading) if c['task_id'] in TARGETS]
    output.mkdir(parents=True, exist_ok=False)
    records = registry(cases)
    (output / 'registry.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    prior_path = ROOT / '.tmp/real-defects/symbol-directed-repair-v1-explicit/experiment.json'
    prior = json.loads(prior_path.read_text(encoding='utf-8'))
    if not prior['complete'] or prior['protocol']['protocol'] != 'symbol-directed-repair-v1':
        raise ValueError('Expected complete frozen previous experiment')
    report = {'protocol': 'repair-public-checks-audit-v1', 'complete': False, 'model_calls': 0,
              'implementation_sha256': repair.audit.sha(Path(__file__)),
              'prior_experiment_sha256': repair.audit.sha(prior_path), 'registry': records, 'tasks': []}
    for case, grade in selected:
        name = case['task_id']
        root = output / name
        root.mkdir()
        harness = root / 'harness'
        frozen = freeze_harness(name, harness, records[name])
        before, _ = check_public(case['before'], harness, frozen, root / 'original', grade['python'], name)
        witness = root / 'positive-example'
        shutil.copytree(case['before'], witness)
        apply_witness(case, witness)
        _, patch = changes(repair.snapshot(case['before']), repair.snapshot(witness))
        (root / 'positive-example.diff').write_text(patch, encoding='utf-8')
        positive, _ = check_public(witness, harness, frozen, root / 'positive-check', grade['python'], name)
        candidates = []
        for row in prior['runs']:
            if row['task_id'] != name:
                continue
            branch = prior_path.parent / f"repeat-{row['repeat']:02d}" / name / row['policy']
            response = branch / 'response.txt'
            workspace = root / f"failed-{row['repeat']}-{row['policy']}"
            shutil.copytree(case['before'], workspace)
            job = json.loads((branch / 'job.json').read_text(encoding='utf-8'))
            apply_symbol_patch(response.read_text(encoding='utf-8'), workspace, case['allowed_files'], job['evidence'])
            outcome, _ = check_public(workspace, harness, frozen, workspace.with_name(workspace.name + '-check'), grade['python'], name)
            candidates.append({'repeat': row['repeat'], 'policy': row['policy'], 'response_sha256': repair.audit.sha(response),
                               'outcome': outcome})
        valid = valid_failure(before) and positive['passed'] and len(candidates) == 6 and all(
            valid_failure(c['outcome']) for c in candidates)
        report['tasks'].append({'task_id': name, 'original': before, 'positive': positive, 'failed_candidates': candidates,
                                'source_hash': case['before_hash'], 'harness_hash': frozen, 'ready': valid})
    report['complete'] = all(r['ready'] for r in report['tasks']) and len(report['tasks']) == 2
    (output / 'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not report['complete']:
        raise ValueError('Public checks failed offline validation; do not run model experiments')
    print(json.dumps({'complete': report['complete'], 'tasks': [{'task_id': r['task_id'], 'ready': r['ready']} for r in report['tasks']]}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    audit(parser.parse_args().output.resolve())
