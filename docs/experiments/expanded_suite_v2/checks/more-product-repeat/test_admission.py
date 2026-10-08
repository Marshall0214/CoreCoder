import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        self.assertEqual(m.nth_product(3,iter('AB'),repeat=2),('B','B'))
        self.assertEqual(m.product_index(('B','B'),iter('AB'),repeat=2),3)

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(m.nth_product(1,'AB','CD'),('A','D'))
        self.assertEqual(m.product_index(('A','D'),'AB','CD'),1)
