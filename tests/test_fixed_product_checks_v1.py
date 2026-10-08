import sys
import types
import unittest

from docs.experiments import fixed_product_checks_v1 as checks


def test_equal_but_wrong_candidate_outputs_cannot_satisfy_fixed_expectations(monkeypatch):
    fake = types.ModuleType('more_itertools')
    fake.gray_product = fake.partial_product = lambda *args, **kwargs: iter([(2, 8, 3, 9)])
    monkeypatch.setitem(sys.modules, 'more_itertools', fake)
    row = {'api': 'partial_product', 'pools': [[2, 3], [8, 9]], 'repeat': 2,
           'expected': [[2, 8, 2, 8]]}
    # The old relational check accepts two identical wrong results.
    assert list(fake.partial_product([2, 3], [8, 9], repeat=2)) == list(
        fake.partial_product(iter([2, 3]), iter([8, 9]), repeat=2))
    module = types.ModuleType('fixed_public_checks')
    # Exercise only our generated test code with a controlled fake package.
    exec(compile(checks.render([row]), '<fixed checks>', 'exec'), module.__dict__)  # noqa: S102
    for group in ('Reproduce', 'Preserve'):
        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(getattr(module, group)).run(result)
        assert result.testsRun == 1 and len(result.failures) == 1 and not result.errors


def test_generated_expected_literals_are_detached_from_oracle_builder_values():
    rows = [{'api': 'partial_product', 'pools': [[2, 3]], 'repeat': 2, 'expected': [[2, 2]]}]
    code = checks.render(rows)
    rows[0]['expected'][0][:] = [9, 9]
    assert "'expected': [(2, 2)]" in code
    assert '(9, 9)' not in code
    compile(code, '<fixed checks>', 'exec')
