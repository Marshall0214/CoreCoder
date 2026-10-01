import unittest
from service import build_request


class TargetTests(unittest.TestCase):
    def test_default_timeout(self):
        self.assertEqual(build_request("/x", {})["timeout_ms"], 5000)

    def test_fractional_and_zero_timeout(self):
        for seconds, milliseconds in [(2, 2000), (0.25, 250), (0, 0)]:
            with self.subTest(seconds=seconds):
                value = build_request("/x", {"timeout_seconds": seconds})["timeout_ms"]
                self.assertEqual(value, milliseconds)
                self.assertIsInstance(value, int)
