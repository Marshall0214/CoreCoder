import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        with self.assertRaises(IndexError):
            m.nth_permutation('ABC',5,0)

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(m.nth_permutation('ABC',2,0),('A','B'))
        with self.assertRaises(ValueError):
            m.nth_permutation('ABC',-1,0)
