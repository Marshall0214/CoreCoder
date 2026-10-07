import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        import more_itertools as mi
        r=mi.numeric_range(0,7)
        for key in (slice(None,None,-1),slice(5,1,-2),slice(-1,None,-2)):
            self.assertEqual(list(r[key]),list(range(7))[key])

class Controls(unittest.TestCase):
    def test_preservation(self):
        import more_itertools as mi
        r=mi.numeric_range(0,7)
        self.assertEqual(list(r[1:6:2]),[1,3,5])
        self.assertEqual(r[-1],6)
