import unittest
from service import build_request
from settings import parse_settings


class RegressionTests(unittest.TestCase):
    def test_url_is_preserved(self):
        self.assertEqual(build_request("/health", {})["url"], "/health")

    def test_settings_remain_seconds(self):
        self.assertEqual(parse_settings({"timeout_seconds": 2}).timeout_seconds, 2.0)
