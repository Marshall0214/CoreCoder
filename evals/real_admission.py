"""Pinned upstream source admission; no model calls and no shared-environment installs."""

import argparse
import hashlib
import importlib.metadata
import io
import json
import re
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


def load_cases():
    cases = json.loads((DATA / 'candidates.json').read_text(encoding='utf-8'))['cases']
    ids = set()
    for case in cases:
        if (not re.fullmatch(r'[a-z0-9-]+', case['case_id']) or case['case_id'] in ids
                or case['repo'] != 'pallets/click' or case['test_directory'] != case['case_id']):
            raise ValueError('Invalid admission candidate')
        ids.add(case['case_id'])
        if not all(re.fullmatch('[0-9a-f]{40}', case[field]) for field in ('before_commit', 'after_commit')):
            raise ValueError('Candidate must pin full commit hashes')
    return cases


def execute(source, checks, group, output):
    output.mkdir(parents=True, exist_ok=True)
    outcome = run_process([sys.executable, '-I', '-B', '-c', BOOTSTRAP,
                           str((source / 'src').resolve()), str(checks.resolve()), group],
                          source, 30, output / (group + '.stdout.txt'), output / (group + '.stderr.txt'),
                          test_environment(source))
    text = (output / (group + '.stderr.txt')).read_text(encoding='utf-8', errors='replace')
    count = re.search(r'Ran (\d+) tests?', text)
    outcome.update(tests_run=int(count.group(1)) if count else 0,
                   assertion_failure=bool(re.search(r'^FAIL: ', text, re.MULTILINE)),
                   execution_error=bool(re.search(r'^ERROR: ', text, re.MULTILINE)),
                   stdout=group + '.stdout.txt', stderr=group + '.stderr.txt')
    outcome['passed'] = outcome['returncode'] == 0 and not outcome['timed_out'] and outcome['tests_run'] > 0
    return outcome


def admit(case, root):
    directory = root / case['case_id']
    directory.mkdir()
    metadata = json.loads(fetch(f"https://api.github.com/repos/{case['repo']}/commits/{case['after_commit']}"))
    if metadata['sha'] != case['after_commit'] or metadata['parents'][0]['sha'] != case['before_commit']:
        raise ValueError('Pinned fix is not a direct child of the original commit')
    changed = [f['filename'] for f in metadata['files'] if f['filename'].startswith('src/') and f['filename'].endswith('.py')]
    if changed != case['changed_source_files']:
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
        groups = {group: execute(revision, checks, group, directory / (label + '-logs')) for group in ('Target', 'Controls')}
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
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory for source snapshots and evidence')
    args = parser.parse_args()
    cases = load_cases()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'purpose': 'development admission; not model repair or held-out performance',
              'python': sys.version, 'platform': sys.platform,
              'catalog_hash': hashlib.sha256((DATA / 'candidates.json').read_bytes()).hexdigest(),
              'admission_code_hash': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'environment_installations': [], 'dependency_versions': {}, 'cases': []}
    for name in ('colorama', 'typing_extensions'):
        try:
            report['dependency_versions'][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report['dependency_versions'][name] = None
    for case in cases:
        try:
            row = admit(case, output)
        except Exception as exc:  # noqa: BLE001 - preserve failed admission evidence, not a repair score
            row = dict(case, admitted=False, admission_error=str(exc))
        report['cases'].append(row)
        (output / 'admission.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"{case['case_id']}: {'admitted' if row['admitted'] else 'not_admitted'}", flush=True)
    return 0 if all(row['admitted'] for row in report['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
