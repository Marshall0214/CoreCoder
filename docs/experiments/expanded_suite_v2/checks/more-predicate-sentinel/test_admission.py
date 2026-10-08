import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        seen=[]
        def pred(*args):
            seen.extend(args)
            return False
        list(m.locate([1,2],pred,window_size=3))
        self.assertTrue(all(isinstance(v,int) for v in seen))
        seen.clear()
        self.assertEqual(list(m.replace([1,2],pred,[9],window_size=3)),[1,2])
        self.assertTrue(all(isinstance(v,int) for v in seen))

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(list(m.locate([0,1,0,1])),[1,3])
        self.assertEqual(list(m.replace([1,2,1],lambda x:x==1,[9])),[9,2,9])
