import io
import zipfile

import pytest

from evals.real_admission import execute, extract_archive, load_cases
from evals.runner import digest, snapshot


def archive_bytes(names):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, content in names:
            archive.writestr(zipfile.ZipInfo(name) if isinstance(name, str) else name, content)
    return stream.getvalue()


@pytest.mark.parametrize('name', ['repo/../escape.py', '/repo/file.py', 'repo/C:/file.py', '.'])
def test_archive_rejects_unsafe_paths_before_writing(tmp_path, name):
    destination = tmp_path / 'source'
    with pytest.raises(ValueError):
        extract_archive(archive_bytes([(name, 'unsafe')]), destination)
    assert not destination.exists()


def test_archive_rejects_raw_backslash_paths(tmp_path):
    # ZipInfo normalizes Windows separators when constructing archives; patch both headers.
    data = archive_bytes([('repo/file.py', 'unsafe')]).replace(b'repo/file.py', b'repo\\file.py')
    with pytest.raises(ValueError):
        extract_archive(data, tmp_path / 'source')


def test_archive_rejects_symlinks(tmp_path):
    entry = zipfile.ZipInfo('repo/link')
    entry.create_system = 3
    entry.external_attr = 0o120777 << 16
    with pytest.raises(ValueError):
        extract_archive(archive_bytes([(entry, '../outside')]), tmp_path / 'source')


def test_archive_rejects_windows_case_collisions(tmp_path):
    with pytest.raises(ValueError):
        extract_archive(archive_bytes([('repo/A.py', 'a'), ('repo/a.py', 'b')]), tmp_path / 'source')


def test_archive_retains_license_and_source(tmp_path):
    destination = tmp_path / 'source'
    extract_archive(archive_bytes([('repo/LICENSE.txt', 'license'), ('repo/src/click/core.py', 'source')]), destination)
    assert (destination / 'LICENSE.txt').read_text() == 'license'
    assert (destination / 'src/click/core.py').read_text() == 'source'


def test_isolated_execution_selects_groups_without_mutating_source(tmp_path):
    source = tmp_path / 'source'
    package = source / 'src/click'
    package.mkdir(parents=True)
    (package / '__init__.py').write_text('PINNED = True\n', encoding='utf-8')
    checks = tmp_path / 'checks'
    checks.mkdir()
    (checks / 'test_admission.py').write_text(
        'import unittest, click\n'
        'class Target(unittest.TestCase):\n'
        '    def test_original_bug(self): self.assertFalse(click.PINNED)\n'
        'class Controls(unittest.TestCase):\n'
        '    def test_import(self): self.assertTrue(click.PINNED)\n', encoding='utf-8')
    original = digest(snapshot(source))
    logs = tmp_path / 'logs'
    target = execute(source, checks, 'Target', logs)
    controls = execute(source, checks, 'Controls', logs)
    assert target['tests_run'] == controls['tests_run'] == 1
    assert target['assertion_failure'] and not target['execution_error'] and not target['passed']
    assert controls['passed']
    assert digest(snapshot(source)) == original
    assert str(package.resolve()) in (logs / 'Target.stdout.txt').read_text(encoding='utf-8')


def test_candidate_catalog_is_development_only():
    cases = load_cases()
    assert len(cases) == 3
    assert all('not a cross-file' in case['repair_scope'] for case in cases)
