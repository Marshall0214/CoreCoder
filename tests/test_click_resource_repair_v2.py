import ast

import pytest

from docs.experiments import click_resource_repair_v2 as repair


def test_preserves_existing_checks_and_adds_three_to_correct_group():
    source = '''import unittest
import click
class Reproduce(unittest.TestCase):
    def test_target(self): pass
class Preserve(unittest.TestCase):
    def test_original(self): pass
'''
    classes = {n.name: n for n in ast.parse(repair.extend_checks(source, 'Preserve')).body if isinstance(n, ast.ClassDef)}
    assert [n.name for n in classes['Reproduce'].body] == ['test_target']
    assert {n.name for n in classes['Preserve'].body} == {
        'test_original', 'test_normal_exit_pops_context', 'test_nested_exit_restores_outer_context',
        'test_exceptional_exit_pops_context'}


@pytest.mark.parametrize('source', [
    'class Other: pass', 'class Preserve: pass\nclass Preserve: pass',
    'class Preserve:\n def test_normal_exit_pops_context(self): pass',
])
def test_invalid_group_or_collision_never_overwrites_checks(source):
    with pytest.raises(ValueError):
        repair.extend_checks(source, 'Preserve')


def group(passed, count, failures=0):
    return {'passed': passed, 'tests_run': count, 'timed_out': False, 'failures': failures, 'errors': 0}


def certification():
    public = {'before': {'Reproduce': group(False, 1, 1), 'Preserve': group(True, 4)},
              'after': {'Reproduce': group(True, 1), 'Preserve': group(True, 4)}}
    private = {'before': {'Target': group(False, 2, 1), 'Controls': group(True, 4)},
               'reference': {'Target': group(True, 2), 'Controls': group(True, 4)}}
    bad_public = {'Reproduce': group(True, 1), 'Preserve': group(False, 4, 3)}
    bad_private = {'Target': group(True, 2), 'Controls': group(False, 4, 3)}
    return public, private, bad_public, bad_private


def test_protocol_requires_known_bad_patch_rejection():
    args = certification()
    assert repair.admitted(*args)
    args[3]['Controls']['passed'] = True
    assert not repair.admitted(*args)


@pytest.mark.parametrize('change', ['zero_tests', 'timeout', 'reference_failure', 'healthy_before_failure'])
def test_incomplete_or_incorrect_certification_blocks_inference(change):
    public, private, bad_public, bad_private = certification()
    if change == 'zero_tests':
        public['before']['Preserve']['tests_run'] = 0
    elif change == 'timeout':
        bad_private['Controls']['timed_out'] = True
    elif change == 'reference_failure':
        private['reference']['Controls']['passed'] = False
    else:
        private['before']['Controls']['passed'] = False
    assert not repair.admitted(public, private, bad_public, bad_private)
