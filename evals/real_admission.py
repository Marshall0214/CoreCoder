"""Pinned upstream source admission; no model calls and no shared-environment installs."""

import argparse
import hashlib
import io
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from .process import run_process, test_environment
from .runner import digest, snapshot

DATA = Path(__file__).parent / 'real_defects'
BOOTSTRAP = '''import pathlib, sys, unittest
source = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(source))
import click
assert pathlib.Path(click.__file__).resolve().is_relative_to(source), "Installed package shadowed source"
print("SOURCE_ORIGIN=" + str(pathlib.Path(click.__file__).resolve()))
suite = unittest.defaultTestLoader.discover(sys.argv[2], pattern="test_admission.py")
selected = unittest.TestSuite()
def select(items):
    for item in items:
        if isinstance(item, unittest.TestSuite):
            select(item)
        elif item.__class__.__name__ == sys.argv[3]:
            selected.addTest(item)
select(suite)
result = unittest.TextTestRunner(verbosity=2).run(selected)
sys.exit(0 if result.wasSuccessful() and result.testsRun else 1)
'''


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'CoreCoder-real-defect-admission'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(32_000_001)
    if len(data) > 32_000_000:
        raise ValueError('Download exceeds admission size limit')
    return data


def extract_archive(data, destination):
    members = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        total, prefixes, seen = 0, set(), set()
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if (not path.parts or '\\' in entry.orig_filename or path.is_absolute() or '..' in path.parts
                    or any(':' in p for p in path.parts) or (entry.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('Unsafe source archive member')
            prefixes.add(path.parts[0])
            if entry.is_dir() or len(path.parts) < 2:
                continue
            relative = Path(*path.parts[1:])
            if relative.as_posix().casefold() in seen or entry.file_size > 1_000_000:
                raise ValueError('Duplicate or oversized source member')
            total += entry.file_size
            if total > 64_000_000:
                raise ValueError('Expanded archive exceeds size limit')
            seen.add(relative.as_posix().casefold())
            members.append((entry, relative))
        if len(prefixes) != 1 or not members:
            raise ValueError('Expected one nonempty repository archive')
        destination.mkdir(parents=True, exist_ok=False)
        for entry, relative in members:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(entry))


def load_cases(catalog=None):
    cases = json.loads((catalog or DATA / 'candidates.json').read_text(encoding='utf-8'))['cases']
    ids = set()
    for case in cases:
        if (not re.fullmatch(r'[a-z0-9-]+', case['case_id']) or case['case_id'] in ids
                or case['repo'] != 'pallets/click' or case['test_directory'] != case['case_id']):
            raise ValueError('Invalid admission candidate')
        ids.add(case['case_id'])
        if not all(re.fullmatch('[0-9a-f]{40}', case[field]) for field in ('before_commit', 'after_commit')):
            raise ValueError('Candidate must pin full commit hashes')
        changed = case['changed_source_files']
        if (not changed or len(set(changed)) != len(changed)
                or any(not re.fullmatch(r'src/click/[a-z_]+\.py', name) for name in changed)):
            raise ValueError('Invalid pinned source repair scope')
    return cases


def execute(source, checks, group, output, python=None, timeout=30):
    output.mkdir(parents=True, exist_ok=True)
    outcome = run_process([str(python or sys.executable), '-I', '-B', '-c', BOOTSTRAP,
                           str((source / 'src').resolve()), str(checks.resolve()), group],
                          source, timeout, output / (group + '.stdout.txt'), output / (group + '.stderr.txt'),
                          test_environment(source))
    text = (output / (group + '.stderr.txt')).read_text(encoding='utf-8', errors='replace')
    count = re.search(r'Ran (\d+) tests?', text)
    outcome.update(tests_run=int(count.group(1)) if count else 0,
                   assertion_failure=bool(re.search(r'^FAIL: ', text, re.MULTILINE)),
                   execution_error=bool(re.search(r'^ERROR: ', text, re.MULTILINE)),
                   stdout=group + '.stdout.txt', stderr=group + '.stderr.txt')
    outcome['passed'] = outcome['returncode'] == 0 and not outcome['timed_out'] and outcome['tests_run'] > 0
    return outcome


def checked_groups(source, checks, logs, python=None, timeout=30):
    source_hash, checks_hash = digest(snapshot(source)), digest(snapshot(checks))
    groups = {group: execute(source, checks, group, logs, python, timeout) for group in ('Target', 'Controls')}
    if source_hash != digest(snapshot(source)) or checks_hash != digest(snapshot(checks)):
        raise ValueError('Source snapshot or admission tests changed during execution')
    return groups


def partial_repairs(case, directory, checks, python=None):
    """Diagnostic of the known upstream patch, not proof of a minimal repair."""
    results = []
    for index, name in enumerate(case['changed_source_files']):
        source = directory / f'partial-{index + 1}'
        shutil.copytree(directory / 'before', source)
        (source / name).write_bytes((directory / 'after' / name).read_bytes())
        results.append({'applied_files': [name], 'tree_hash': digest(snapshot(source)),
                        'groups': checked_groups(source, checks, directory / f'partial-{index + 1}-logs', python)})
    return results


def admit(case, root, python=None):
    directory = root / case['case_id']
    directory.mkdir()
    metadata = json.loads(fetch(f"https://api.github.com/repos/{case['repo']}/commits/{case['after_commit']}"))
    if metadata['sha'] != case['after_commit'] or metadata['parents'][0]['sha'] != case['before_commit']:
        raise ValueError('Pinned fix is not a direct child of the original commit')
    changed = [f['filename'] for f in metadata['files'] if f['filename'].startswith('src/') and f['filename'].endswith('.py')]
    if sorted(changed) != sorted(case['changed_source_files']):
        raise ValueError('Source repair scope differs from catalog')
    (directory / 'commit-metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    checks = DATA / 'checks' / case['test_directory']
    row = dict(case, checks_hash=digest(snapshot(checks)), revisions={})
    for label in ('before', 'after'):
        commit = case[label + '_commit']
        archive = fetch(f"https://codeload.github.com/{case['repo']}/zip/{commit}")
        (directory / (label + '.zip')).write_bytes(archive)
        revision = directory / label
        extract_archive(archive, revision)
        license_file = revision / 'LICENSE.txt'
        license_text = license_file.read_text(encoding='utf-8')
        if not all(part in ' '.join(license_text.split()) for part in ('Copyright', 'Redistribution', '3. Neither')):
            raise ValueError('License text requires review')
        tree_hash = digest(snapshot(revision))
        groups = checked_groups(revision, checks, directory / (label + '-logs'), python)
        if tree_hash != digest(snapshot(revision)) or row['checks_hash'] != digest(snapshot(checks)):
            raise ValueError('Source snapshot or admission tests changed during execution')
        row['revisions'][label] = {'archive_sha256': hashlib.sha256(archive).hexdigest(),
                                   'tree_hash': tree_hash, 'license_sha256': hashlib.sha256(license_file.read_bytes()).hexdigest(),
                                   'groups': groups}
    before, after = (row['revisions'][label]['groups'] for label in ('before', 'after'))
    target = before['Target']
    row['admitted'] = (not target['passed'] and target['assertion_failure'] and not target['execution_error']
                       and not target['timed_out'] and target['tests_run'] > 0
                       and before['Controls']['passed'] and after['Target']['passed'] and after['Controls']['passed'])
    if case.get('partial_repair_diagnostics'):
        row['partial_repairs'] = partial_repairs(case, directory, checks, python)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory for source snapshots and evidence')
    parser.add_argument('--catalog', type=Path, default=DATA / 'candidates.json')
    parser.add_argument('--python', type=Path, help='Explicit test interpreter, e.g. a dedicated dependency-free venv')
    args = parser.parse_args()
    cases = load_cases(args.catalog)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'purpose': 'development admission; not model repair or held-out performance',
              'python': sys.version, 'platform': sys.platform,
              'catalog_hash': hashlib.sha256(args.catalog.read_bytes()).hexdigest(),
              'admission_code_hash': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'environment_installations': [], 'dependency_versions': {}, 'cases': []}
    python = args.python.resolve() if args.python else Path(sys.executable)
    metadata_code = '''import importlib.metadata, json, sys
versions = {}
for name in ("colorama", "typing_extensions"):
    try: versions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError: versions[name] = None
print(json.dumps(dict(python=sys.version, executable=sys.executable, prefix=sys.prefix,
                     base_prefix=sys.base_prefix, dependency_versions=versions)))
'''
    info = run_process([str(python), '-I', '-B', '-c', metadata_code], output, 15,
                       output / 'environment.json', output / 'environment.stderr.txt', test_environment(output))
    if info['returncode'] != 0 or info['timed_out']:
        raise ValueError('Cannot inspect test interpreter; see environment.stderr.txt')
    report['test_environment'] = json.loads((output / 'environment.json').read_text(encoding='utf-8'))
    report['dependency_versions'] = report['test_environment']['dependency_versions']
    for case in cases:
        try:
            row = admit(case, output, python)
        except Exception as exc:  # noqa: BLE001 - preserve failed admission evidence, not a repair score
            row = dict(case, admitted=False, admission_error=str(exc))
        report['cases'].append(row)
        (output / 'admission.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"{case['case_id']}: {'admitted' if row['admitted'] else 'not_admitted'}", flush=True)
    return 0 if all(row['admitted'] for row in report['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
