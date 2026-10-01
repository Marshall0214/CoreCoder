import unittest
from service import query_dates


class RegressionTests(unittest.TestCase):
    def test_start_is_included(self):
        self.assertEqual(query_dates(["2026-01-01"], "2026-01-01", "2026-01-03"), ["2026-01-01"])

    def test_before_start_is_excluded(self):
        self.assertEqual(query_dates(["2025-12-31"], "2026-01-01", "2026-01-03"), [])
