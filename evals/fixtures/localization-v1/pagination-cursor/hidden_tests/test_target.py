import unittest

from api import browse_records


class TargetTests(unittest.TestCase):
    def collect(self, rows, limit):
        cursor, result = None, []
        for _ in range(len(rows) + 2):
            page = browse_records(rows, limit, cursor)
            result.extend(row["id"] for row in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return result
            self.assertIsInstance(cursor, str)
        self.fail("pagination did not terminate")

    def test_equal_timestamps(self):
        rows = [{"created": "2026-01-01", "id": identity} for identity in ["d", "b", "a", "c"]]
        for limit in (1, 2, 3):
            with self.subTest(limit=limit):
                self.assertEqual(self.collect(rows, limit), ["a", "b", "c", "d"])

    def test_distinct_timestamps_no_lookahead_skip(self):
        rows = [{"created": f"2026-01-0{i}", "id": str(i)} for i in range(1, 7)]
        self.assertEqual(self.collect(rows, 2), ["1", "2", "3", "4", "5", "6"])

    def test_empty_and_exact_page(self):
        self.assertEqual(browse_records([], 2), {"items": [], "next_cursor": None})
        rows = [{"created": "2026-01-01", "id": "a"}, {"created": "2026-01-01", "id": "b"}]
        self.assertIsNone(browse_records(rows, 2)["next_cursor"])

    def test_input_not_mutated(self):
        rows = [{"created": "2026-01-01", "id": "b"}, {"created": "2025-01-01", "id": "a"}]
        original = [dict(row) for row in rows]
        self.collect(rows, 1)
        self.assertEqual(rows, original)
