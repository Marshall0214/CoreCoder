import unittest
from service import next_action


class TargetTests(unittest.TestCase):
    def test_permanent_failures_stop(self):
        for status in [400, 401, 403, 404, 422]:
            with self.subTest(status=status):
                self.assertEqual(next_action({"status": status}), "stop")

    def test_transient_failures_retry(self):
        for status in [429, 500, 503, 599]:
            with self.subTest(status=status):
                self.assertEqual(next_action({"status": status}), "retry")
