import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        from boltons.iterutils import split
        self.assertEqual(split([1,None,3],maxsplit=0), [[1,None,3]])
        self.assertEqual(split(iter([1,None,3]),maxsplit=0), [[1,None,3]])

class Controls(unittest.TestCase):
    def test_preservation(self):
        from boltons.iterutils import split
        self.assertEqual(split([1,None,3]), [[1],[3]])
        self.assertEqual(split([1,2]), [[1,2]])
