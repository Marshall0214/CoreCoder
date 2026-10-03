import unittest

from acquire import acquire
from cleanup import sweep
from legacy import old_batch_expired
from models import Lease
from monitor import list_tenant
from renew import renew
from store import Store


class VisibleTests(unittest.TestCase):
    def test_creation_and_live_conflict(self):
        store = Store()
        self.assertTrue(acquire(store, "a", "job", "alice", 0, 1000))
        self.assertFalse(acquire(store, "a", "job", "bob", 0.1, 1000))
        self.assertEqual(list_tenant(store, "a")[0][:2], ("job", "alice"))

    def test_single_tenant_renewal_and_cleanup(self):
        store = Store()
        store.put(Lease("a", "job", "alice", 2))
        self.assertTrue(renew(store, "a", "job", "alice", 1, 1000))
        self.assertEqual(sweep(store, 3), [("a", "job")])
        self.assertFalse(old_batch_expired(2, 2))
