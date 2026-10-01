import unittest
from service import next_action
from policy import is_retryable


class RegressionTests(unittest.TestCase):
    def test_success(self):
        self.assertEqual(next_action({"status": 200}), "done")

    def test_policy(self):
        self.assertTrue(is_retryable(429))
        self.assertFalse(is_retryable(404))
