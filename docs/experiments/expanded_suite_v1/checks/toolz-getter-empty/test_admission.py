import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        from toolz.itertoolz import getter
        self.assertEqual(getter([])('hello'), ())
        self.assertEqual(getter([])([]), ())

class Controls(unittest.TestCase):
    def test_preservation(self):
        from toolz.itertoolz import getter
        self.assertEqual(getter(1)('hello'), 'e')
        self.assertEqual(getter([1])('hello'), ('e',))
