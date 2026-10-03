import unittest

from acquire import acquire
from cleanup import sweep
from legacy import old_batch_expired
from models import Lease
from renew import renew
from store import Store


class TargetTests(unittest.TestCase):
    def test_creation_units_and_expired_reacquisition(self):
        store = Store()
        self.assertTrue(acquire(store, "a", "job", "alice", 10, 500))
        self.assertEqual(store.get("a", "job").expires_at, 10.5)
        self.assertFalse(acquire(store, "a", "job", "bob", 10.49, 500))
        self.assertTrue(acquire(store, "a", "job", "bob", 10.5, 250))
        self.assertEqual(store.get("a", "job").expires_at, 10.75)

    def test_renewal_is_tenant_scoped_even_with_same_owner(self):
        store = Store()
        first = Lease("a", "job", "worker", 5)
        store.put(first)
        store.put(Lease("b", "job", "worker", 8))
        self.assertTrue(renew(store, "b", "job", "worker", 1, 500))
        self.assertEqual(store.get("a", "job"), first)
        self.assertEqual(store.get("b", "job").expires_at, 1.5)
        self.assertFalse(renew(store, "missing", "job", "worker", 1, 500))

    def test_cleanup_boundary_agrees_with_authorization(self):
        store = Store()
        store.put(Lease("a", "equal", "worker", 2))
        store.put(Lease("a", "old", "worker", 1))
        store.put(Lease("b", "live", "worker", 3))
        self.assertFalse(renew(store, "a", "equal", "worker", 2, 1000))
        self.assertEqual(sweep(store, 2), [("a", "equal"), ("a", "old")])
        self.assertEqual(len(store.all()), 1)
        self.assertFalse(old_batch_expired(2, 2))

    def test_lifecycle_preserves_unrelated_and_rejected_rows(self):
        store = Store()
        protected = Lease("other", "shared", "worker", 20)
        store.put(protected)
        self.assertTrue(acquire(store, "new", "shared", "worker", 5, 500))
        self.assertTrue(renew(store, "new", "shared", "worker", 5.25, 500))
        self.assertFalse(renew(store, "new", "shared", "intruder", 5.3, 500))
        self.assertEqual(store.get("new", "shared").expires_at, 5.75)
        self.assertEqual(sweep(store, 5.75), [("new", "shared")])
        self.assertEqual(store.all(), [protected])
