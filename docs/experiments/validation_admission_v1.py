"""Admit a fixed post-design Click validation pool without changing the engine."""

import argparse
import hashlib
import json
from pathlib import Path

from docs.experiments.real_retrieval_audit_v1 import ENGINE, ROOT, sha
from evals.process import run_process, test_environment
from evals.real_admission import checked_groups, extract_archive, fetch, load_cases
from evals.runner import digest, implementation_metadata, snapshot

CATALOG = Path(__file__).with_name('validation-candidates-v1.json')
CHECKS = Path(__file__).with_name('validation_checks_v1')
PR_NUMBERS = (3434, 3493, 3677)


def frozen_inputs(catalog=CATALOG, checks_root=CHECKS):
    document = json.loads(catalog.read_text(encoding='utf-8'))
    cases = load_cases(catalog)
    if document['selection']['frozen_pool'] != list(PR_NUMBERS) or len(cases) != 3:
        raise ValueError('Expected the fixed three-candidate validation pool')
    old = []
    for name in ('candidates.json', 'crossfile-candidates.json', 'expansion-candidates-v1.json'):
        old.extend(load_cases(ROOT / 'evals/real_defects' / name))
    old_ids = {c['case_id'] for c in old}
    old_fixes = {c['after_commit'] for c in old}
    for case, number in zip(cases, PR_NUMBERS):
        if case['case_id'] in old_ids or case['after_commit'] in old_fixes:
            raise ValueError('Candidate overlaps a development task')
        if case['fix_url'] != f'https://github.com/pallets/click/pull/{number}':
            raise ValueError('Candidate PR order changed')
        checks = checks_root / case['test_directory']
        if not (checks / 'test_admission.py').is_file():
            raise ValueError('Candidate needs Target and Controls checks')
    if implementation_metadata()['source_hash'] != ENGINE:
        raise ValueError('Frozen engine changed')
    return cases, {'catalog_sha256': sha(catalog), 'checks_sha256': digest(snapshot(checks_root)),
                   'engine_hash': ENGINE, 'adapter_sha256': sha(Path(__file__))}


def eligible(row):
    before, after = (row['revisions'][label]['groups'] for label in ('before', 'after'))
    target = before['Target']
    return (not target['passed'] and target['assertion_failure'] and not target['execution_error']
            and not target['timed_out'] and target['tests_run'] > 0 and before['Controls']['passed']
            and after['Target']['passed'] and after['Controls']['passed'])


def admit(case, output, checks_root, python):
    root = output / case['case_id']
    root.mkdir()
    checks = checks_root / case['test_directory']
    check_hash = digest(snapshot(checks))
    metadata = json.loads(fetch(f"https://api.github.com/repos/{case['repo']}/commits/{case['after_commit']}"))
    if metadata['sha'] != case['after_commit'] or metadata['parents'][0]['sha'] != case['before_commit']:
        raise ValueError('Fix is not a direct child of the pinned before commit')
    changed = sorted(f['filename'] for f in metadata['files'] if f['filename'].startswith('src/') and f['filename'].endswith('.py'))
    if changed != sorted(case['changed_source_files']):
        raise ValueError('Pinned source scope differs from upstream commit')
    (root / 'commit-metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    row = dict(case, checks_hash=check_hash, revisions={})
    for label in ('before', 'after'):
        archive = fetch(f"https://codeload.github.com/{case['repo']}/zip/{case[label + '_commit']}")
        (root / (label + '.zip')).write_bytes(archive)
        source = root / label
        extract_archive(archive, source)
        license_file = source / 'LICENSE.txt'
        text = ' '.join(license_file.read_text(encoding='utf-8').split())
        if not all(part in text for part in ('Copyright', 'Redistribution', '3. Neither')):
            raise ValueError('License requires review')
        tree_hash = digest(snapshot(source))
        groups = checked_groups(source, checks, root / (label + '-logs'), python, 15)
        if digest(snapshot(source)) != tree_hash or digest(snapshot(checks)) != check_hash:
            raise ValueError('Source or checks changed during admission')
        row['revisions'][label] = {'archive_sha256': hashlib.sha256(archive).hexdigest(),
                                   'tree_hash': tree_hash, 'license_sha256': sha(license_file), 'groups': groups}
    row['admitted'] = eligible(row)
    row['exclusion_reason'] = None if row['admitted'] else 'Required before/after Target and Controls behavior did not reproduce'
    return row


def run(output, python, catalog=CATALOG, checks_root=CHECKS):
    cases, identities = frozen_inputs(catalog, checks_root)
    output, python = output.resolve(), python.resolve()
    if output.exists() or output.is_relative_to(checks_root.resolve()):
        raise ValueError('Use a fresh output outside checks')
    output.mkdir(parents=True)
    protocol = dict(identities, protocol='validation-admission-v1', repair_llm_calls=0, embedding_calls=0,
                    selection=json.loads(catalog.read_text(encoding='utf-8'))['selection'],
                    candidate_ids=[c['case_id'] for c in cases], checks_root=str(checks_root.resolve()),
                    catalog=str(catalog.resolve()), scoring='Target and Controls; not full upstream tests')
    (output / 'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    # No shared-environment installs; require the existing isolated stdlib test interpreter.
    script = '''import importlib.metadata, json, sys
versions = {}
for name in ('colorama', 'typing_extensions'):
    try: versions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError: versions[name] = None
print(json.dumps(dict(executable=sys.executable, python=sys.version, prefix=sys.prefix,
                     base_prefix=sys.base_prefix, dependency_versions=versions)))
'''
    result = run_process([str(python), '-I', '-B', '-c', script], output, 15,
                         output / 'environment.json', output / 'environment.stderr.txt', test_environment(output))
    if result['returncode'] or result['timed_out']:
        raise ValueError('Cannot inspect isolated interpreter')
    environment = json.loads((output / 'environment.json').read_text(encoding='utf-8'))
    if environment['prefix'] == environment['base_prefix'] or any(environment['dependency_versions'].values()):
        raise ValueError('Use the isolated dependency-free Click test environment')
    report = {'protocol': protocol, 'test_environment': environment, 'catalog_hash': identities['catalog_sha256'],
              'environment_installations': [], 'cases': [], 'complete': False,
              'repair_llm_calls': 0, 'embedding_calls': 0}

    def save():
        (output / 'admission.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    for case in cases:
        current_cases, current = frozen_inputs(catalog, checks_root)
        if current != identities or current_cases != cases:
            raise ValueError('Frozen admission inputs changed')
        try:
            row = admit(case, output, checks_root, python)
        except Exception as exc:  # noqa: BLE001 - preserve every candidate and environmental exclusion
            row = dict(case, admitted=False, exclusion_reason=f'{type(exc).__name__}: {exc}')
        report['cases'].append(row)
        save()
        print(f"{case['case_id']}: {'admitted' if row['admitted'] else 'not_admitted'}", flush=True)
    if frozen_inputs(catalog, checks_root)[1] != identities:
        raise ValueError('Admission inputs changed after verification')
    report.update(complete=len(report['cases']) == 3, admitted_count=sum(r['admitted'] for r in report['cases']))
    save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.output, args.python)
    raise SystemExit(0 if report['admitted_count'] == 3 else 1)


if __name__ == '__main__':
    main()
