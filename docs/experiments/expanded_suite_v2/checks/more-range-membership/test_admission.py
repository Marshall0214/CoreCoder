import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        r=m.numeric_range(0.0,1.0,0.1)
        for i,v in enumerate(r):
            self.assertIn(v,r)
            self.assertEqual(r.index(v),i)
        r=m.numeric_range(-8.732,-13.532,-2.4)
        self.assertEqual(len(r),len([v for v in r]))

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(list(m.numeric_range(1,7,2)),[1,3,5])
        self.assertNotIn(2,m.numeric_range(1,7,2))
