import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        import more_itertools as mi
        s=mi.seekable([4,5,6],maxlen=0)
        self.assertEqual(s.peek(),4)
        self.assertEqual(s.peek(),4)
        self.assertEqual(list(s),[4,5,6])
        s=mi.seekable([1,2],maxlen=0)
        self.assertTrue(s)
        self.assertEqual(list(s),[1,2])

class Controls(unittest.TestCase):
    def test_preservation(self):
        import more_itertools as mi
        s=mi.seekable([4,5],maxlen=2)
        self.assertEqual(s.peek(),4)
        self.assertEqual(list(s),[4,5])
        self.assertFalse(mi.seekable([],maxlen=0))
