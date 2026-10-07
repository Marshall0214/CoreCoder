import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        from boltons.iterutils import remap
        self.assertEqual(remap({2,4,6}), {2,4,6})
        self.assertEqual(remap(frozenset([2,4])), frozenset([2,4]))

class Controls(unittest.TestCase):
    def test_preservation(self):
        from boltons.iterutils import remap
        self.assertEqual(remap({'a':[1,2]}), {'a':[1,2]})
        self.assertEqual(remap([1,2]), [1,2])
