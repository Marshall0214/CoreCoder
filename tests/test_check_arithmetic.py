from decimal import Decimal

import pytest

from evals.check_arithmetic import calculate, numeric_assertions, validate_numeric_proofs


@pytest.mark.parametrize("expression,expected", [
    ("round_half_up(100 * 5 / 10000)", "0"),
    ("round_half_up(300 * 10 / 10000)", "0"),
    ("round_half_up(1.005 * 1 * 100)", "101"),
    ("round_half_up(100 * 50 / 10000)", "1"),
    ("-2 + +3 * 4 / 2", "4"),
    ("min(3,2)=2", "2"),
    ("max(0,3-2) = 1", "1"),
])
def test_bounded_decimal_arithmetic(expression, expected):
    assert calculate(expression) == Decimal(expected)


@pytest.mark.parametrize("expression", ["1 / 0", "2 ** 99", "open('x')", "__import__('os')",
                                         "x + 1", "round_half_up(1, 2)", "1e999", "True", "[1][0]",
                                         "min(3,2)=3", "1==1", "min([3,2])", "max(x,1)"])
def test_unsupported_or_invalid_arithmetic(expression):
    with pytest.raises(ValueError):
        calculate(expression)


def test_numeric_assertions_keep_original_call_indices_and_skip_bool():
    code = "class Check:\n def test_x(self):\n  self.assertEqual(x, 'a')\n  self.assertEqual(y, 1)\n  self.assertEqual(z, True)\n"
    assert numeric_assertions(code) == {"Check.test_x": [{"assertion": 1, "expected": 1}]}


def test_arithmetic_mismatch_rejects_original_false_expectation():
    with pytest.raises(ValueError, match="differs from expected"):
        validate_numeric_proofs([{"assertion": 0, "expression": "round_half_up(100 * 5 / 10000)"}],
                                [{"assertion": 0, "expected": 1}])


@pytest.mark.parametrize("proofs", [[], [{"assertion": 8, "expression": "1"}],
                                    [{"assertion": True, "expression": "1"}]])
def test_missing_unknown_and_boolean_proof_ids_rejected(proofs):
    with pytest.raises(ValueError):
        validate_numeric_proofs(proofs, [{"assertion": 0, "expected": 1}])
