import unittest

from boltons import iterutils as m


class Target(unittest.TestCase):
    def test_contract(self):
        self.assertEqual(m.backoff(0,8),[0.0,1.0,2.0,4.0,8.0])

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(m.backoff(1,8),[1.0,2.0,4.0,8.0])
        self.assertEqual(m.backoff(1,8,count=2),[1.0,2.0])
