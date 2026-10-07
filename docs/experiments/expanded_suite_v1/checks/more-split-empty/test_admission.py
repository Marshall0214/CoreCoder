import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        import more_itertools as mi
        self.assertEqual(list(mi.split_before([],bool,maxsplit=0)),[])
        self.assertEqual(list(mi.split_after([],bool,maxsplit=0)),[])
        self.assertEqual(list(mi.split_when([],lambda a,b:a!=b,maxsplit=0)),[])

class Controls(unittest.TestCase):
    def test_preservation(self):
        import more_itertools as mi
        self.assertEqual(list(mi.split_before([1,2],bool,maxsplit=0)),[[1,2]])
        self.assertEqual(list(mi.split_after([1,2],bool,maxsplit=0)),[[1,2]])
        self.assertEqual(list(mi.split_when([1,2],lambda a,b:a!=b,maxsplit=0)),[[1,2]])
