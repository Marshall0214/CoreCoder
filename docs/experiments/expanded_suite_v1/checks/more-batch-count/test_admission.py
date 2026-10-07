import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        import more_itertools as mi
        for limit in (0,-1):
            with self.assertRaises(ValueError): list(mi.constrained_batches([b'a'],10,max_count=limit))

class Controls(unittest.TestCase):
    def test_preservation(self):
        import more_itertools as mi
        self.assertEqual(list(mi.constrained_batches([b'a',b'b',b'c'],10,max_count=2)),[(b'a',b'b'),(b'c',)])
        self.assertEqual(list(mi.constrained_batches([b'a',b'b'],10)),[(b'a',b'b')])
