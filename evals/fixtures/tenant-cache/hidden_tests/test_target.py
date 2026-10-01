import unittest
from service import save_session
from store import SessionStore


class TargetTests(unittest.TestCase):
    def test_cross_tenant_isolation(self):
        store = SessionStore()
        save_session(store, "a", "u", "first")
        save_session(store, "b", "u", "second")
        self.assertEqual(store.get("a", "u"), "first")
        self.assertEqual(store.get("b", "u"), "second")

    def test_delimiter_collision(self):
        store = SessionStore()
        save_session(store, "a:b", "c", "first")
        save_session(store, "a", "b:c", "second")
        self.assertEqual(store.get("a:b", "c"), "first")
        self.assertEqual(store.get("a", "b:c"), "second")
