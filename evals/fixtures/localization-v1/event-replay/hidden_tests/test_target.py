import unittest

from gateway import replay_batch


def event(tenant, identity, delta):
    return {"tenant": tenant, "event_id": identity, "delta": delta}


class TargetTests(unittest.TestCase):
    def test_same_id_different_tenants(self):
        self.assertEqual(replay_batch({}, set(), [event("a", "x", 2), event("b", "x", 3)]),
                         {"a": 2, "b": 3})

    def test_duplicate_does_not_drop_tail(self):
        self.assertEqual(replay_batch({}, set(), [event("a", "x", 2), event("a", "x", 2),
                                                  event("a", "y", 3)]), {"a": 5})

    def test_persistent_batches(self):
        state, seen = {}, set()
        replay_batch(state, seen, [event("a", "x", 2)])
        replay_batch(state, seen, [event("a", "x", 2), event("b", "x", 4), event("a", "y", -1)])
        self.assertEqual(state, {"a": 1, "b": 4})
        replay_batch(state, seen, [event("a", "x", 2), event("a", "y", -1)])
        self.assertEqual(state, {"a": 1, "b": 4})

    def test_identifiers_with_separators(self):
        self.assertEqual(replay_batch({}, set(), [event("a:b", "c", 1), event("a", "b:c", 2)]),
                         {"a:b": 1, "a": 2})
