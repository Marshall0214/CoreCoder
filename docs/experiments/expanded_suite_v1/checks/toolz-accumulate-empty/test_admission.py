import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        from toolz import accumulate
        from operator import add
        self.assertEqual(list(accumulate(add, [])), [])

class Controls(unittest.TestCase):
    def test_preservation(self):
        from toolz import accumulate
        from operator import add
        self.assertEqual(list(accumulate(add, [2,3,4])), [2,5,9])
        self.assertEqual(list(accumulate(add, [], 7)), [7])
