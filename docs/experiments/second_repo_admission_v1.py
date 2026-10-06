"""Admit a fixed second-repository pool without modifying the frozen engine."""

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

from docs.experiments import validation_admission_v1 as prior
from docs.experiments.real_retrieval_audit_v1 import ENGINE, sha
from evals.process import run_process, test_environment
from evals.real_admission import BOOTSTRAP, extract_archive, fetch
from evals.runner import digest, implementation_metadata, snapshot

CATALOG = Path(__file__).with_name('second-repo-candidates-v1.json')
CHECKS = Path(__file__).with_name('second_repo_checks_v1')
IDS = ('itsdangerous-none-salt', 'itsdangerous-future-age', 'itsdangerous-malformed-time')
eligible = prior.eligible
BOOT = BOOTSTRAP.replace('click', 'itsdangerous').replace(
    'sys.exit(0 if result.wasSuccessful() and result.testsRun else 1)',
    'for name, module in list(sys.modules.items()):\n'
    '    if name == "itsdangerous" or name.startswith("itsdangerous."):\n'
    '        assert pathlib.Path(module.__file__).resolve().is_relative_to(source), "Submodule shadowed source"\n'
    'sys.exit(0 if result.wasSuccessful() and result.testsRun else 1)')


def frozen_inputs(catalog=CATALOG, checks_root=CHECKS):
    document = json.loads(catalog.read_text(encoding='utf-8'))
    cases = document['cases']
    if tuple(c['case_id'] for c in cases) != IDS:
        raise ValueError('Expected fixed three-candidate pool')
    for case in cases:
        if (case['repo'] != 'pallets/itsdangerous' or case['package'] != 'itsdangerous'
                or case['test_directory'] != case['case_id']
                or not all(re.fullmatch('[0-9a-f]{40}', case[k]) for k in ('before_commit', 'after_commit'))
                or not case['changed_source_files']
                or len(set(case['changed_source_files'])) != len(case['changed_source_files'])
                or any(not re.fullmatch(r'src/itsdangerous/[a-z_]+\.py', p) for p in case['changed_source_files'])
                or not (checks_root / case['test_directory'] / 'test_admission.py').is_file()):
            raise ValueError('Invalid candidate identity or scope')
    if implementation_metadata()['source_hash'] != ENGINE:
        raise ValueError('Frozen engine changed')
    return cases, {'catalog_sha256': sha(catalog), 'checks_sha256': digest(snapshot(checks_root)),
                   'engine_hash': ENGINE, 'adapter_sha256': sha(Path(__file__))}


def checked_groups(source, checks, logs, python, timeout=15):
    source_hash, checks_hash = digest(snapshot(source)), digest(snapshot(checks))
    logs.mkdir(parents=True, exist_ok=True)
    groups = {}
    for group in ('Target', 'Controls'):
        stderr = logs / (group + '.stderr.txt')
        outcome = run_process([str(python), '-I', '-B', '-c', BOOT, str((source / 'src').resolve()),
                               str(checks.resolve()), group], source, timeout,
                              logs / (group + '.stdout.txt'), stderr, test_environment(source))
        text = stderr.read_text(encoding='utf-8', errors='replace')
        count = re.search(r'Ran (\d+) tests?', text)
        outcome.update(tests_run=int(count.group(1)) if count else 0,
                       assertion_failure=bool(re.search(r'^FAIL: ', text, re.MULTILINE)),
                       execution_error=bool(re.search(r'^ERROR: ', text, re.MULTILINE)))
        outcome['passed'] = outcome['returncode'] == 0 and not outcome['timed_out'] and outcome['tests_run'] > 0
        groups[group] = outcome
    if source_hash != digest(snapshot(source)) or checks_hash != digest(snapshot(checks)):
        raise ValueError('Source or checks changed during verification')
    return groups


def public_tasks(cases, report, output):
    tasks = []
    for case, row in zip(cases, report['cases']):
        if row['admitted']:
            source = output / case['case_id'] / 'before'
            tasks.append({'task_id': case['case_id'], 'repo': case['repo'], 'before_commit': case['before_commit'],
                          'description': case['public_problem'],
                          'allowed_files': sorted(p for p in snapshot(source) if p.startswith('src/itsdangerous/') and p.endswith('.py'))})
    return {'tasks': tasks}


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
        license_file = source / 'LICENSE.rst'
        text = ' '.join(license_file.read_text(encoding='utf-8').split())
        if not all(part in text for part in ('Copyright', 'Redistribution', '3. Neither')):
            raise ValueError('License requires review')
        tree_hash = digest(snapshot(source))
        groups = checked_groups(source, checks, root / (label + '-logs'), python, 15)
        if digest(snapshot(source)) != tree_hash or digest(snapshot(checks)) != check_hash:
            raise ValueError('Source or checks changed during admission')
        row['revisions'][label] = {'archive_sha256': hashlib.sha256(archive).hexdigest(),
                                   'tree_hash': tree_hash, 'license_sha256': sha(license_file), 'groups': groups}
    if case.get('partial_repair_diagnostics'):
        row['partial_repairs'] = []
        for index, name in enumerate(case['changed_source_files']):
            source = root / f'partial-{index + 1}'
            shutil.copytree(root / 'before', source)
            (source / name).write_bytes((root / 'after' / name).read_bytes())
            row['partial_repairs'].append({'applied_files': [name], 'tree_hash': digest(snapshot(source)),
                                           'groups': checked_groups(source, checks, root / f'partial-{index + 1}-logs', python, 15)})
    if any(digest(snapshot(root / label)) != row['revisions'][label]['tree_hash'] for label in ('before', 'after')):
        raise ValueError('Original snapshots changed during partial diagnostics')
    row['admitted'] = eligible(row)
    row['exclusion_reason'] = None if row['admitted'] else 'Required before/after Target and Controls behavior did not reproduce'
    return row


def run(output, python, catalog=CATALOG, checks_root=CHECKS):
    cases, identities = frozen_inputs(catalog, checks_root)
    output, python = output.resolve(), python.resolve()
    if output.exists() or output.is_relative_to(checks_root.resolve()):
        raise ValueError('Use a fresh output outside checks')
    output.mkdir(parents=True)
    protocol = dict(identities, protocol='second-repo-admission-v1', repair_llm_calls=0, embedding_calls=0,
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
        raise ValueError('Use the isolated dependency-free test environment')
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
    (output / 'public-tasks.json').write_text(json.dumps(public_tasks(cases, report, output), indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.output, args.python)
    raise SystemExit(0 if report['admitted_count'] == 3 else 1)
