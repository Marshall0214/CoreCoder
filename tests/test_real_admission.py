import io
import zipfile

import pytest

from evals.real_admission import DATA, execute, extract_archive, load_cases, partial_repairs
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


def test_crossfile_catalog_pins_two_behavioral_source_files():
    cases = load_cases(DATA / 'crossfile-candidates.json')
    assert len(cases) == 1
    assert cases[0]['partial_repair_diagnostics'] is True
    assert set(cases[0]['changed_source_files']) == {'src/click/core.py', 'src/click/types.py'}


def test_expansion_catalog_has_disjoint_complete_development_checks():
    import ast
    import json

    catalog = DATA / 'expansion-candidates-v1.json'
    assert 'development admission only' in json.loads(catalog.read_text())['purpose']
    existing = load_cases() + load_cases(DATA / 'crossfile-candidates.json')
    cases = load_cases(catalog)
    assert not ({case['case_id'] for case in cases} & {case['case_id'] for case in existing})
    for case in cases:
        assert 'development only' in case['provenance']
        assert 'not a cross-file' in case['repair_scope']
        tree = ast.parse((DATA / 'checks' / case['test_directory'] / 'test_admission.py').read_text())
        groups = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        for name in ('Target', 'Controls'):
            assert any(isinstance(node, ast.FunctionDef) and node.name.startswith('test_')
                       for node in groups[name].body)


def test_partial_repairs_overlay_one_file_and_preserve_originals(tmp_path, monkeypatch):
    files = ['src/click/core.py', 'src/click/types.py']
    for label in ('before', 'after'):
        for name in files:
            path = tmp_path / label / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(label + name, encoding='utf-8')
        (tmp_path / label / 'LICENSE.txt').write_text('retained license', encoding='utf-8')
    original = {label: digest(snapshot(tmp_path / label)) for label in ('before', 'after')}
    seen = []

    def groups(source, checks, logs, python):
        seen.append([name for name in files if (source / name).read_bytes() == (tmp_path / 'after' / name).read_bytes()])
        assert (source / 'LICENSE.txt').read_text() == 'retained license'
        return {'Target': {'passed': False}, 'Controls': {'passed': True}}

    monkeypatch.setattr('evals.real_admission.checked_groups', groups)
    rows = partial_repairs({'changed_source_files': files}, tmp_path, tmp_path / 'checks')
    assert seen == [[files[0]], [files[1]]]
    assert [row['applied_files'] for row in rows] == seen
    assert {label: digest(snapshot(tmp_path / label)) for label in original} == original
