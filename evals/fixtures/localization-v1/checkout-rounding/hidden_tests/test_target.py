import unittest

from checkout import submit_order


class TargetTests(unittest.TestCase):
    def test_half_cent_line(self):
        self.assertEqual(submit_order([("1.005", 1)])["subtotal_minor"], 101)

    def test_half_cent_discount(self):
        self.assertEqual(submit_order([("1.01", 1)], 5000)["discount_minor"], 51)

    def test_quantity_before_rounding(self):
        self.assertEqual(submit_order([("0.335", 3)])["payable_minor"], 101)

    def test_round_each_line_before_summing(self):
        self.assertEqual(submit_order([("0.005", 1), ("0.005", 1)], 5000),
                         {"subtotal_minor": 2, "discount_minor": 1, "payable_minor": 1})

    def test_empty_and_full_discount(self):
        self.assertEqual(submit_order([])["payable_minor"], 0)
        self.assertEqual(submit_order([("1.005", 1)], 10000)["payable_minor"], 0)
