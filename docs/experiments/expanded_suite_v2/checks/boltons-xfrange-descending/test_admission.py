import unittest

from boltons import iterutils as m


class Target(unittest.TestCase):
    def test_contract(self):
        self.assertEqual(list(m.xfrange(5,0,step=-1.25)),[5.0,3.75,2.5,1.25])
        self.assertEqual(list(m.xfrange(1.0,step=0.1)),m.frange(1.0,step=0.1))

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(list(m.xfrange(4)),[0.0,1.0,2.0,3.0])
