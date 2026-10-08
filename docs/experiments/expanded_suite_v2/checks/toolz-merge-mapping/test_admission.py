import unittest

import toolz as m


class Target(unittest.TestCase):
    def test_contract(self):
        from collections import UserDict
        self.assertEqual(m.merge_with(sum,UserDict({'x':3})),{'x':3})

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(m.merge_with(sum,{'x':1},{'x':2,'y':4}),{'x':3,'y':4})
