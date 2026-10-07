import unittest
from toolz import join

class Target(unittest.TestCase):
    def test_contract(self):
        self.assertCountEqual(list(join(0,[(1,'a'),(2,'b')],0,[(1,'x')],right_default=None)),
                              [((1,'a'),(1,'x')),((2,'b'),None)])

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(list(join(0,[(1,'a'),(2,'b')],0,[(1,'x')])),[((1,'a'),(1,'x'))])
