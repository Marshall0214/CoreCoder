import unittest
from service import save_session
from store import SessionStore


class RegressionTests(unittest.TestCase):
    def test_same_tenant_roundtrip(self):
        store = SessionStore()
        self.assertEqual(save_session(store, "a", "u", "token"), "token")

    def test_missing_session(self):
        self.assertIsNone(SessionStore().get("a", "u"))
