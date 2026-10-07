import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        import more_itertools as mi
        self.assertEqual(list(reversed(mi.numeric_range(0))),[])
        self.assertEqual(list(reversed(mi.numeric_range(2,2))),[])

class Controls(unittest.TestCase):
    def test_preservation(self):
        import more_itertools as mi
        self.assertEqual(list(reversed(mi.numeric_range(0,5,2))),[4,2,0])
        self.assertEqual(list(mi.numeric_range(0,5,2)),[0,2,4])
