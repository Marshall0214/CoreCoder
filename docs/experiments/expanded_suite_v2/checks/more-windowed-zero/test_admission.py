import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        for size in (0,-1):
            for seq in ([],[1,2]):
                with self.assertRaises(ValueError):
                    list(m.windowed(seq,size))

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(list(m.windowed([1,2,3],2)),[(1,2),(2,3)])
        self.assertEqual(list(m.windowed([1],2)),[(1,None)])
