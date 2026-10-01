import unittest

from jobs import run_job
from clock import VirtualClock


class TargetTests(unittest.TestCase):
    def test_attempt_timeout_capped(self):
        clock, observed = VirtualClock(), []
        def call(timeout):
            observed.append(timeout)
            clock.advance(timeout)
            return 503
        result = run_job(call, clock, total_timeout=2, attempt_timeout=10)
        self.assertEqual(observed, [2])
        self.assertEqual(result, {"status": "deadline", "attempts": 1, "elapsed": 2.0})

    def test_wait_capped(self):
        clock = VirtualClock()
        def call(timeout):
            clock.advance(1)
            return 503
        result = run_job(call, clock, total_timeout=2, attempt_timeout=1, backoff=10)
        self.assertEqual(result, {"status": "deadline", "attempts": 1, "elapsed": 2.0})

    def test_later_attempt_uses_remaining_budget(self):
        clock, observed = VirtualClock(), []
        def call(timeout):
            observed.append(timeout)
            clock.advance(timeout)
            return 429
        result = run_job(call, clock, total_timeout=5, attempt_timeout=3, max_attempts=5, backoff=1)
        self.assertEqual(observed, [3, 1])
        self.assertEqual(result, {"status": "deadline", "attempts": 2, "elapsed": 5.0})

    def test_success_after_retry(self):
        clock, responses = VirtualClock(), iter([503, 200])
        def call(timeout):
            clock.advance(min(0.5, timeout))
            return next(responses)
        self.assertEqual(run_job(call, clock, backoff=1),
                         {"status": "done", "attempts": 2, "elapsed": 2.0})
