import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        import more_itertools as mi
        from itertools import combinations_with_replacement
        pool=[0,None,2]
        for i,c in enumerate(combinations_with_replacement(pool,2)):
            self.assertEqual(mi.combination_with_replacement_index(c,pool),i)

class Controls(unittest.TestCase):
    def test_preservation(self):
        import more_itertools as mi
        self.assertEqual(mi.combination_with_replacement_index([],[]),0)
        self.assertEqual(mi.combination_with_replacement_index([1,1],[0,1,2]),3)
        with self.assertRaises(ValueError): mi.combination_with_replacement_index([3],[0,1])
