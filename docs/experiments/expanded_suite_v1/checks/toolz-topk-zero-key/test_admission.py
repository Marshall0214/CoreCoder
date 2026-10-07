import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        from toolz import topk
        self.assertEqual(topk(2, [(1,9),(4,2),(3,8)], key=0), ((4,2),(3,8)))

class Controls(unittest.TestCase):
    def test_preservation(self):
        from toolz import topk
        self.assertEqual(topk(2, [1,4,3]), (4,3))
        self.assertEqual(topk(1, ['a','bbbb','cc'], key=len), ('bbbb',))
