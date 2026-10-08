import unittest

from boltons import iterutils as m


class Target(unittest.TestCase):
    def test_contract(self):
        from itertools import islice
        repeat=''.join(['re','peat'])  # noqa: FLY002 - object identity is the regression
        self.assertEqual(list(islice(m.backoff_iter(1,4,count=repeat),5)),[1.0,2.0,4.0,4.0,4.0])

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(list(m.backoff_iter(1,4,count=2)),[1.0,2.0])
