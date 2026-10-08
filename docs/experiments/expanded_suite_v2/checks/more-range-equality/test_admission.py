import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        a=m.numeric_range(2,3,1);b=m.numeric_range(2,3,5)
        self.assertEqual(a,b)
        self.assertEqual(hash(a),hash(b))

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertNotEqual(m.numeric_range(0,5,2),m.numeric_range(0,7,2))
        self.assertEqual(m.numeric_range(0),m.numeric_range(3,3))
