import json
import unittest

import pytest

from docs.experiments.frozen_assertions_v1 import render

SOURCE = '''import unittest
def normal():
    return [1, 2]
def defective():
    return [1]
class Reproduce(unittest.TestCase):
    def test_behavior(self):
        expected = normal()
        self.assertEqual(defective(), expected)
class Preserve(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(normal(), [1, 2])
'''


def run(code):
    namespace = {'__name__': 'frozen_checks'}
    exec(compile(code, '<test>', 'exec'), namespace)  # noqa: S102 - locally authored fixture only
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(namespace[group])
                               for group in ('Reproduce', 'Preserve'))
    result = unittest.TestResult()
    suite.run(result)
    return result


def frozen(tmp_path, source=SOURCE):
    path = tmp_path / 'observations.json'
    code, _ = render(source, mode='record', output=path)
    run(code)
    return json.loads(path.read_text())


def test_candidate_cannot_change_both_sides_into_false_success(tmp_path):
    observations = frozen(tmp_path)
    bad = SOURCE.replace('return [1, 2]', 'return [9]').replace('return [1]', 'return [9]')
    verify, _ = render(bad, mode='verify', observations=observations)
    result = run(verify)
    assert len(result.failures) == 2
    assert not result.wasSuccessful()


def test_correct_repair_passes_without_recomputing_expected(tmp_path):
    observations = frozen(tmp_path)
    good = SOURCE.replace('return [1]\n', 'return [1, 2]\n')
    code, _ = render(good, mode='verify', observations=observations)
    assert run(code).wasSuccessful()


def test_defective_actual_not_called_while_recording_expectations(tmp_path):
    code = SOURCE.replace('return [1]\n', 'raise RuntimeError("defect")\n')
    observations = frozen(tmp_path, code)
    values = [value for key, value in observations.items() if key.startswith('Reproduce@')]
    assert values == [[['list', [['int', 1], ['int', 2]]]]]


def test_loop_observations_are_ordered_and_missing_calls_fail(tmp_path):
    source = SOURCE.replace('self.assertEqual(normal(), [1, 2])',
                            'for value in normal():\n            self.assertEqual(value, value)')
    observations = frozen(tmp_path, source)
    bad = source.replace('return [1, 2]', 'return [1]')
    code, _ = render(bad, mode='verify', observations=observations)
    result = run(code)
    assert any('observation missing' in trace for _, trace in result.failures)


def test_set_order_and_type_round_trip(tmp_path):
    source = SOURCE.replace('[1, 2]', '{(1, b"a"), (2, b"b")}').replace('[1]', '{(1, b"a")}')
    observations = frozen(tmp_path, source)
    good = source.replace('return {(1, b"a")}\n', 'return {(2, b"b"), (1, b"a")}\n')
    code, _ = render(good, mode='verify', observations=observations)
    assert run(code).wasSuccessful()


def test_preserve_snapshot_distinguishes_bool_from_int(tmp_path):
    source = SOURCE.replace('return [1, 2]', 'return [True, 2]')
    observations = frozen(tmp_path, source)
    bad = source.replace('return [True, 2]', 'return [1, 2]')
    code, _ = render(bad, mode='verify', observations=observations)
    assert not run(code).wasSuccessful()


@pytest.mark.parametrize('replacement', ['object()', '[[[[[[[[[[[[[[[[[[[[[[[1]]]]]]]]]]]]]]]]]]]]]]]'])
def test_unsupported_or_excessive_values_do_not_produce_accepted_checks(tmp_path, replacement):
    source = SOURCE.replace('return [1, 2]', 'return ' + replacement)
    path = tmp_path / 'observations.json'
    code, _ = render(source, mode='record', output=path)
    assert not run(code).wasSuccessful()


def test_original_source_and_checks_are_not_modified(tmp_path):
    frozen(tmp_path)
    assert SOURCE.endswith('self.assertEqual(normal(), [1, 2])\n')
    assert '_cc_' not in SOURCE


@pytest.mark.parametrize('source', [SOURCE + '\n_cc_state = {}', SOURCE.replace('def test_normal(self):', 'def tearDown(self):')])
def test_conflicting_helpers_and_teardown_fail_closed(source):
    with pytest.raises(ValueError):
        render(source, mode='verify', observations={})


def test_future_imports_are_preserved(tmp_path):
    source = '"""Public checks."""\nfrom __future__ import annotations\n' + SOURCE
    observations = frozen(tmp_path, source)
    code, _ = render(source.replace('return [1]\n', 'return [1, 2]\n'), mode='verify', observations=observations)
    assert run(code).wasSuccessful()


def test_literal_expectations_do_not_need_capture_after_original_exception(tmp_path):
    source = '''import unittest
def original():
    return 0
class Reproduce(unittest.TestCase):
    def test_error(self):
        with self.assertRaises(ValueError) as caught:
            original()
        self.assertEqual(str(caught.exception), 'expected')
class Preserve(unittest.TestCase):
    def test_normal(self):
        self.assertEqual([1, 2], [1, 2])
'''
    observations = frozen(tmp_path, source)
    good = source.replace('return 0', "raise ValueError('expected')")
    code, _ = render(good, mode='verify', observations=observations)
    assert run(code).wasSuccessful()
