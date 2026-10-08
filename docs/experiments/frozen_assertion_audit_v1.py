"""Certify reusable frozen public assertions and replay all 50 historical issues."""
import argparse
import hashlib
import json
from pathlib import Path

from docs.experiments import frozen_assertions_v1 as frozen_assertions
from docs.experiments import public_feedback_v2 as policy
from evals.runner import digest, snapshot


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def preserved(outcomes):
    return outcomes.get('Preserve', {}).get('passed', False)


def build_cases(admitted, development, heldout, certificates):
    data = load(admitted)
    if not data['complete'] or len(data['cases']) != 50 or len({c['task_id'] for c in data['cases']}) != 50:
        raise ValueError('Require all 50 frozen admitted cases')
    histories = {'development': development, 'heldout': heldout}
    rows = {}
    for split, path in histories.items():
        report = load(path)
        expected = 30 if split == 'development' else 20
        if not report['complete'] or len(report['runs']) != expected * 2:
            raise ValueError('Incomplete historical run')
        for row in report['runs']:
            key = (row['task_id'], row['policy'])
            if row['split'] != split or row['policy'] not in {'single', 'public-feedback'} or key in rows:
                raise ValueError('Duplicate or invalid historical row')
            rows[key] = row
    by_id = {}
    for path in certificates:
        cert = load(path)
        if not cert['complete'] or cert['admission_hash'] != policy.admission.history.sha(admitted):
            raise ValueError('Invalid public certificates')
        for row in cert['cases']:
            if row['task_id'] in by_id or not row['certified']:
                raise ValueError('Duplicate or uncertified public harness')
            by_id[row['task_id']] = row
    if set(by_id) != {c['task_id'] for c in data['cases']}:
        raise ValueError('Missing public harnesses')
    for case in data['cases']:
        if any((case['task_id'], p) not in rows for p in ('single', 'public-feedback')):
            raise ValueError('Missing historical pair')
        cert = by_id[case['task_id']]
        if cert['description_hash'] != hashlib.sha256(case['description'].encode()).hexdigest():
            raise ValueError('Public description changed')
    return data['cases'], histories, rows, by_id


def run(admitted, development, heldout, certificates, output):
    cases, histories, old_rows, certs = build_cases(admitted, development, heldout, certificates)
    inputs = [admitted, development, heldout, *certificates, Path(__file__), Path(frozen_assertions.__file__), Path(policy.__file__)]
    hashes = {str(path.resolve()): policy.admission.history.sha(path) for path in inputs}
    roots = [Path(c[p]).resolve() for c in cases for p in ('before', 'after', 'checks')]
    roots += [p.parent.resolve() for p in histories.values()] + [Path(c['harness']).resolve() for c in certs.values()]
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in roots):
        raise ValueError('Fresh output outside historical inputs required')
    output.mkdir(parents=True)
    report = {'complete': False, 'model_calls': 0, 'cases': [], 'protocol': {
        'name': 'frozen-assertion-audit-v1', 'input_hashes': hashes,
        'oracle': 'Reproduce expected operands and healthy Preserve actual operands from original public checks',
        'reference': 'offline certification only; no reference-derived expected values',
        'private_grader': 'historical score is reported unchanged, never used to construct observations',
        'limits': 'Existing equality observations only; no new inputs; not a new repair benchmark or blind heldout',
        'before_certification': 'Original Preserve passes; observations nonempty; original Reproduce still fails',
        'after_certification': 'Reference Reproduce and Preserve both pass'}}

    def save():
        certified = [c for c in report['cases'] if c.get('certified')]
        replays = [(c['task_id'], r) for c in certified for r in c['replays']]
        report['summary'] = {'tasks': len(report['cases']), 'certified': len(certified),
                             'excluded': [c['task_id'] for c in report['cases'] if not c.get('certified')],
                             'replayed_candidates': len(replays),
                             'observations': sum(c.get('observations', 0) for c in certified),
                             'historically_scored_success_now_rejected': [{'task_id': t, 'policy': r['policy']}
                                 for t, r in replays if r['historical_accepted'] and not r['frozen_passed']]}
        policy.write_json(output / 'audit.json', report)

    for case in cases:
        if any(policy.admission.history.sha(Path(p)) != h for p, h in hashes.items()):
            raise ValueError('Frozen audit inputs changed')
        for name in ('before', 'after', 'checks'):
            if digest(snapshot(Path(case[name]))) != case[name + '_hash']:
                raise ValueError('Frozen source/checks changed')
        task = case['task_id']
        cert = certs[task]
        harness = Path(cert['harness'])
        if digest(snapshot(harness)) != cert['harness_hash']:
            raise ValueError('Public harness changed')
        source = (harness / 'test_admission.py').read_text(encoding='utf-8')
        root = output / task
        root.mkdir()
        row = {'task_id': task, 'original_split': case['split'], 'certified': False, 'replays': []}
        oracle = root / 'observations.json'
        capture = root / 'capture-checks'
        capture.mkdir()
        try:
            recording, metadata = frozen_assertions.render(source, mode='record', output=oracle)
            (capture / 'test_admission.py').write_text(recording, encoding='utf-8')
            captured = policy.public_check(case['before'], capture, case['package'], case['source_root'], root / 'capture')
            row['capture'] = captured
            observations = load(oracle) if oracle.exists() else {}
            row['observations'] = sum(len(v) for v in observations.values())
            if not preserved(captured) or not observations:
                row['exclusion_reason'] = 'original_preservation_or_capture_failed'
            else:
                checks = root / 'frozen-checks'
                checks.mkdir()
                code, _ = frozen_assertions.render(source, mode='verify', observations=observations)
                (checks / 'test_admission.py').write_text(code, encoding='utf-8')
                row.update(harness=str(checks.resolve()), harness_hash=digest(snapshot(checks)),
                           observation_hash=frozen_assertions.observation_hash(observations), metadata=metadata)
                row['certification'] = {label: policy.public_check(case[label], checks, case['package'], case['source_root'], root / label)
                                        for label in ('before', 'after')}
                row['certified'] = bool(policy.certified(row['certification']))
                if not row['certified']:
                    row['exclusion_reason'] = 'frozen_reference_or_original_certification_failed'
                else:
                    for name, directory in [('single', 'initial-workspace'), ('public-feedback', 'workspace')]:
                        historical = histories[case['split']].parent / task
                        candidate = historical / directory
                        # Check source identity against the historical grading copy before replaying.
                        grading = historical / ('grade-' + name) / 'grading'
                        version = digest(snapshot(candidate))
                        if version != digest(snapshot(grading)):
                            raise ValueError('Historical candidate differs from graded snapshot')
                        outcomes = policy.public_check(candidate, checks, case['package'], case['source_root'], root / name)
                        if version != digest(snapshot(candidate)):
                            raise ValueError('Historical candidate changed')
                        old = old_rows[(task, name)]
                        row['replays'].append({'policy': name, 'candidate_hash': version,
                                               'historical_accepted': old['accepted'],
                                               'frozen_passed': policy.all_pass(outcomes), 'outcomes': outcomes})
        except (ValueError, TypeError, SyntaxError) as exc:
            # Preserve unsupported-case diagnostics; integrity errors stop the audit.
            if 'Historical candidate' in str(exc):
                raise
            row.update(certified=False, exclusion_reason=f'{type(exc).__name__}: {exc}')
        report['cases'].append(row)
        save()
        print(task, 'certified' if row['certified'] else 'excluded', flush=True)
    if any(policy.admission.history.sha(Path(p)) != h for p, h in hashes.items()):
        raise ValueError('Frozen audit inputs changed')
    report['complete'] = len(report['cases']) == 50
    save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admission', type=Path, required=True)
    parser.add_argument('--development', type=Path, required=True)
    parser.add_argument('--heldout', type=Path, required=True)
    parser.add_argument('--certificates', type=Path, nargs=2, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.admission.resolve(), args.development.resolve(), args.heldout.resolve(),
        [p.resolve() for p in args.certificates], args.output.resolve())
