import unittest

from gateway import replay_batch
from export_keys import export_identity
from snapshot import snapshot_counts


class RegressionTests(unittest.TestCase):
    def test_one_batch(self):
        state = replay_batch({}, set(), [{"tenant": "a", "event_id": "x", "delta": 2},
                                         {"tenant": "a", "event_id": "y", "delta": -1}])
        self.assertEqual(state, {"a": 1})

    def test_export_and_snapshot(self):
        self.assertEqual(export_identity({"tenant": "a", "event_id": "x"}), "x")
        self.assertEqual(snapshot_counts({"b": 2, "a": 1}), {"a": 1, "b": 2})
