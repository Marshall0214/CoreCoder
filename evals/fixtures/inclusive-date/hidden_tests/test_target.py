import unittest
from service import query_dates


class TargetTests(unittest.TestCase):
    def test_end_is_included(self):
        result = query_dates(["2026-01-01", "2026-01-03", "2026-01-04"], "2026-01-01", "2026-01-03")
        self.assertEqual(result, ["2026-01-01", "2026-01-03"])

    def test_single_day_and_month_boundary(self):
        self.assertEqual(query_dates(["2026-01-31", "2026-02-01"], "2026-01-31", "2026-01-31"), ["2026-01-31"])
