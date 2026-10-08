import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        b=m.bucket([10,20,11],key=lambda x:x//10)
        self.assertEqual(list(b[3]),[])
        self.assertFalse(4 in b)
        self.assertEqual(set(b),{1,2})

class Controls(unittest.TestCase):
    def test_preservation(self):
        b=m.bucket([10,20,11],key=lambda x:x//10)
        self.assertEqual(list(b[1]),[10,11])
        self.assertEqual(list(b[2]),[20])
