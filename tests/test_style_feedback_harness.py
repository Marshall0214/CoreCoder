"""Validate the versioned development harness without importing candidate code."""
import ast
import runpy
import sys
import types
import unittest
from pathlib import Path

from repairflow.github_issue import config

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / 'configs/issue-tasks/click-3887-style-v1/test_admission.py'


def methods(source, class_name):
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return {node.name: ast.dump(node) for node in cls.body if isinstance(node, ast.FunctionDef)}


def test_original_target_and_controls_are_retained_exactly():
    previous = (ROOT / 'configs/issue-tasks/click-3887/test_admission.py').read_text(encoding='utf-8')
    current = HARNESS.read_text(encoding='utf-8')
    assert methods(previous, 'Reproduce') == methods(current, 'Reproduce')
    assert methods(previous, 'Preserve') == methods(current, 'OriginalPreserve')
    diagnostic = (ROOT / 'evals/diagnostics/click_style_preservation.py').read_text(encoding='utf-8')
    assert methods(diagnostic, 'StylePreservation') == methods(current, 'StylePreservation')


def test_discovery_selects_one_target_and_nine_unique_controls(monkeypatch):
    # Only trusted definitions execute; no Click code or tests run on the host.
    monkeypatch.setitem(sys.modules, 'click', types.ModuleType('click'))
    namespace = runpy.run_path(str(HARNESS), run_name='trusted_style_feedback_harness')
    loader = unittest.TestLoader()
    assert len(loader.getTestCaseNames(namespace['Reproduce'])) == 1
    names = loader.getTestCaseNames(namespace['Preserve'])
    assert len(names) == 9 and len(set(names)) == 9
    namespace['Preserve'].setUpClass()
    assert namespace['Preserve'].click is sys.modules['click']


def test_new_configuration_changes_only_harness_location():
    url = 'https://github.com/pallets/click/issues/3887'
    previous = config(ROOT / 'configs/issue-tasks/click-3887.json', url)
    current = config(ROOT / 'configs/issue-tasks/click-3887-style-v1.json', url)
    for key in ('repo', 'issue_number', 'base_commit', 'package', 'source_root', 'allowed_files',
                'license_file', 'license_id', 'image'):
        assert previous[key] == current[key]
    assert previous['harness'] != current['harness']
    assert previous['harness_sha256'] != current['harness_sha256']
