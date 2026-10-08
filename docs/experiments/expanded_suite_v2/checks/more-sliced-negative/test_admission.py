import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        for strict in (False,True):
            with self.assertRaises(ValueError):
                list(m.sliced('ABCDE',-1,strict=strict))

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(list(m.sliced('ABCDE',2)),['AB','CD','E'])
