"""Offline-only public salt relation matrix, positive witness and mutation validation."""

import argparse
import ast
import hashlib
import json
import re
import shutil
from pathlib import Path

from docs.experiments import repair_forwarding_worker_v1 as forwarding
from docs.experiments import repair_public_checks_v1 as public
from docs.experiments import repair_public_feedback_worker_v1 as previous
from evals.symbol_context import apply_symbol_patch

repair = public.repair
ROOT = public.ROOT
TASK = 'itsdangerous-none-salt'
CHECK = Path(__file__).with_name('public_checks_v2') / 'none_salt.py'
HISTORY = ROOT / '.tmp/real-defects/repair-forwarding-feedback-v1/experiment.json'
MUTATIONS = {
    'serializer_none_wrong_default': ('src/itsdangerous/serializer.py',
        '        self.salt: bytes = want_bytes(salt)',
        '        if salt is None:\n            salt = b"itsdangerous"\n        self.salt: bytes = want_bytes(salt)',
        'test_serializer_none_matches_explicit_signer'),
    'omitted_default_changed': ('src/itsdangerous/serializer.py',
        'salt: _t_str_bytes = b"itsdangerous",', 'salt: _t_str_bytes = b"itsdangerous.Signer",',
        'test_omitted_default_matches_independent_signer'),
    'empty_salt_collapsed': ('src/itsdangerous/serializer.py',
        '        self.salt: bytes = want_bytes(salt)',
        '        self.salt: bytes = want_bytes(salt or b"itsdangerous")',
        'test_explicit_constructor_salt_exact_signature'),
    'instance_salt_ignored': ('src/itsdangerous/serializer.py',
        '        if salt is None:\n            salt = self.salt\n\n        return self.signer',
        '        return self.signer', 'test_omitted_default_matches_independent_signer'),
    'method_override_ignored_signing': ('src/itsdangerous/serializer.py',
        '        if salt is None:\n            salt = self.salt\n\n        return self.signer',
        '        salt = self.salt\n\n        return self.signer', 'test_method_salt_override_matrix'),
    'method_override_ignored_loading': ('src/itsdangerous/serializer.py',
        '        for signer in self.iter_unsigners(salt):',
        '        for signer in self.iter_unsigners(None):', 'test_method_salt_override_matrix'),
}


def mutate(workspace, spec):
    path, old, new, _ = spec
    target = workspace / path
    text = target.read_text(encoding='utf-8')
    if text.count(old) != 1:
        raise ValueError('Mutation anchor must be unique')
    target.write_text(text.replace(old, new), encoding='utf-8')


def failed_methods(output):
    return sorted(set(re.findall(r'^FAIL: (test_\w+)', output, re.MULTILINE)))


def contract(case):
    description = case['description']
    clauses = ['using the Signer default salt rather than the Serializer default',
               'Signed values must round-trip', 'Preserve explicit string and bytes salts',
               'the Serializer default salt', 'wrong-salt rejection', 'tamper detection']
    spans = [{'text': text, 'span': [description.index(text), description.index(text) + len(text)]}
             for text in clauses]
    defaults = {}
    for path, owner in [('src/itsdangerous/serializer.py', 'Serializer'),
                        ('src/itsdangerous/signer.py', 'Signer')]:
        data = (case['before'] / path).read_bytes()
        tree = ast.parse(data)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
        ctor = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
        params = [*ctor.args.posonlyargs, *ctor.args.args]
        values = dict(zip([p.arg for p in params[-len(ctor.args.defaults):]], ctor.args.defaults))
        salt = ast.literal_eval(values['salt'])
        if not isinstance(salt, bytes):
            raise TypeError('Expected literal bytes defaults in original API')
        defaults[owner] = {'salt_utf8': salt.decode(), 'path': path,
            'source_sha256': hashlib.sha256(data).hexdigest(), 'line': ctor.lineno}
    if defaults['Serializer']['salt_utf8'] != 'itsdangerous' or defaults['Signer']['salt_utf8'] != 'itsdangerous.Signer':
        raise ValueError('Original public API defaults changed')
    return {'description': description, 'description_sha256': hashlib.sha256(description.encode()).hexdigest(),
        'clauses': spans, 'original_api_defaults': defaults, 'check_sha256': repair.audit.sha(CHECK),
        'rules': [
            {'constructor': 'omitted', 'method_salt': 'omitted or None', 'effective': 'Serializer original default'},
            {'constructor': 'explicit None', 'method_salt': 'omitted or None', 'effective': 'Signer original default'},
            {'constructor': 'explicit str/bytes including empty', 'method_salt': 'omitted or None', 'effective': 'instance salt'},
            {'constructor': 'any', 'method_salt': 'explicit str/bytes including empty', 'effective': 'method override'}],
        'provenance': 'Human-authored public-description relations plus preservation of original API parameter forwarding; not hidden grading.',
        'preservation_source': ['Serializer.make_signer', 'Serializer.iter_unsigners', 'Serializer.dumps', 'Serializer.loads'],
        'limits': '11 test methods with subtests, not exhaustive semantics, cryptographic proof or general automatic test generation.'}


def audit(output):
    output = output.resolve()
    if output.exists():
        raise ValueError('Use fresh audit output')
    cases, grades = public.comparison.prepare(output)
    case, grade = next((c, g) for c, g in zip(cases, grades) if c['task_id'] == TASK)
    history = json.loads(HISTORY.read_text(encoding='utf-8'))
    if not history['complete'] or history['protocol']['protocol'] != 'repair-forwarding-feedback-v1':
        raise ValueError('Expected frozen complete prior comparison')
    frozen = {str(p.relative_to(ROOT)): repair.audit.sha(p) for p in (
        Path(__file__), CHECK, Path(public.__file__), Path(previous.__file__), Path(forwarding.__file__), HISTORY)}
    report = {'protocol': 'salt-relations-audit-v1', 'complete': False, 'model_calls': 0,
              'contract': contract(case), 'adapter_hashes': frozen, 'source_hash': case['before_hash'],
              'original': None, 'positive': None, 'mutants': [], 'historical_candidates': []}
    output.mkdir(parents=True, exist_ok=False)
    harness = output / 'harness'
    harness.mkdir()
    (harness / 'test_admission.py').write_bytes(CHECK.read_bytes())
    harness_hash = repair.digest(repair.snapshot(harness))

    def checked(workspace, label):
        outcome, _ = public.check_public(workspace, harness, harness_hash, output / label, grade['python'], TASK)
        # Certification diagnoses the complete local log, not the bounded model-feedback excerpt.
        text = (output / label / 'logs' / outcome['stderr']).read_text(encoding='utf-8')
        return {'outcome': outcome, 'failed_methods': failed_methods(text),
                'candidate_source_hash': repair.digest(repair.snapshot(workspace))}

    report['original'] = checked(case['before'], 'original-check')
    positive = output / 'positive-example'
    shutil.copytree(case['before'], positive)
    public.apply_witness(case, positive)
    report['positive'] = checked(positive, 'positive-check')
    for name, spec in MUTATIONS.items():
        workspace = output / ('mutant-' + name)
        shutil.copytree(positive, workspace)
        mutate(workspace, spec)
        result = checked(workspace, name + '-check')
        result.update(name=name, expected_failed_method=spec[3])
        result['detected'] = public.valid_failure(result['outcome']) and spec[3] in result['failed_methods']
        report['mutants'].append(result)
    for row in history['runs']:
        if row['task_id'] != TASK:
            continue
        branch = HISTORY.parent / f"repeat-{row['repeat']:02d}" / TASK / row['policy']
        job = json.loads((branch / 'job.json').read_text(encoding='utf-8'))
        workspace = output / f"historical-{row['repeat']}-{row['policy']}"
        shutil.copytree(case['before'], workspace)
        initial, feedback = branch / 'response.txt', branch / 'feedback-response.txt'
        apply_symbol_patch(initial.read_text(encoding='utf-8'), workspace, case['allowed_files'], job['evidence'])
        packed = (forwarding.forwarding_context(workspace, case['allowed_files'], job['evidence'], case['description'])
                  if row['policy'] == 'forwarding-feedback' else previous.refresh_seeds(
                      workspace, case['allowed_files'], job['evidence']))
        apply_symbol_patch(feedback.read_text(encoding='utf-8'), workspace, case['allowed_files'], packed['evidence'])
        result = checked(workspace, workspace.name + '-check')
        result.update(repeat=row['repeat'], policy=row['policy'], initial_sha256=repair.audit.sha(initial),
                      feedback_sha256=repair.audit.sha(feedback), detected=public.valid_failure(result['outcome']))
        report['historical_candidates'].append(result)
    if (repair.digest(repair.snapshot(case['before'])) != case['before_hash']
            or any(repair.audit.sha(ROOT / path) != sha for path, sha in frozen.items())):
        raise ValueError('Frozen source or implementation changed')
    report['complete'] = (public.valid_failure(report['original']['outcome']) and report['positive']['outcome']['passed']
        and len(report['mutants']) == 6 and all(r['detected'] for r in report['mutants'])
        and len(report['historical_candidates']) == 6 and all(r['detected'] for r in report['historical_candidates']))
    (output / 'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not report['complete']:
        raise ValueError('Relation checks did not pass offline certification')
    print(json.dumps({'complete': True, 'model_calls': 0, 'positive_tests': report['positive']['outcome']['tests_run'],
                      'mutants_detected': 6, 'historical_failures_detected': 6}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    audit(parser.parse_args().output)
