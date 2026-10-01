import unittest

from jobs import run_job
from clock import VirtualClock
from backoff_preview import preview_delays


class RegressionTests(unittest.TestCase):
    def test_success_and_client_error(self):
        self.assertEqual(run_job(lambda timeout: 200, VirtualClock()),
                         {"status": "done", "attempts": 1, "elapsed": 0.0})
        self.assertEqual(run_job(lambda timeout: 400, VirtualClock())["status"], "stopped")

    def test_attempt_limit_and_preview(self):
        self.assertEqual(run_job(lambda timeout: 503, VirtualClock(), max_attempts=1)["status"], "attempt_limit")
        self.assertEqual(preview_delays(2, 3), [2, 4, 8])
