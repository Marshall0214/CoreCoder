import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        self.assertEqual(m.nth_combination_with_replacement('AB',3,0),('A','A','A'))
        self.assertEqual(m.nth_combination_with_replacement([],0,0),())
        with self.assertRaises(IndexError):
            m.nth_combination_with_replacement([],2,0)

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(m.nth_combination_with_replacement('ABC',2,1),('A','B'))
