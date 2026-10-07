import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        import more_itertools as mi
        self.assertEqual(list(mi.interleave_evenly([])),[])
        self.assertEqual(list(mi.interleave_evenly([],lengths=[])),[])

class Controls(unittest.TestCase):
    def test_preservation(self):
        import more_itertools as mi
        self.assertEqual(list(mi.interleave_evenly([[1,3],[2,4]])),[1,2,3,4])
