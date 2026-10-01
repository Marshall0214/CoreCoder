import unittest

from api import browse_records
from offset_paging import offset_page
from feed import newest_first


class RegressionTests(unittest.TestCase):
    def test_single_page(self):
        rows = [{"created": "2026-01-01", "id": "b"}, {"created": "2025-01-01", "id": "a"}]
        self.assertEqual(browse_records(rows, 3), {"items": [rows[1], rows[0]], "next_cursor": None})

    def test_other_endpoints(self):
        rows = [{"created": "2025-01-01", "id": "a"}, {"created": "2026-01-01", "id": "b"}]
        self.assertEqual(offset_page(rows, 1, 1), [rows[1]])
        self.assertEqual(newest_first(rows), [rows[1], rows[0]])
