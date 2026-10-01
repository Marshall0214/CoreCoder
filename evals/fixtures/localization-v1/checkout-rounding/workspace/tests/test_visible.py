import unittest

from checkout import submit_order
from legacy_report import report_minor
from display import format_minor


class RegressionTests(unittest.TestCase):
    def test_regular_order(self):
        self.assertEqual(submit_order([("2.00", 2)], 2500),
                         {"subtotal_minor": 400, "discount_minor": 100, "payable_minor": 300})

    def test_legacy_and_display(self):
        self.assertEqual(report_minor("1.005"), 100)
        self.assertEqual(format_minor(123), "1.23")
