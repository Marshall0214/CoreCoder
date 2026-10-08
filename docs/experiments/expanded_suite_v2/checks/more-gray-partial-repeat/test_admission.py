import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        for fn in (m.gray_product,m.partial_product):
            self.assertEqual(list(fn(iter('AB'),iter('CD'),repeat=2)),list(fn('AB','CD',repeat=2)))

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(list(m.partial_product('AB','CD')),[('A','C'),('B','C'),('B','D')])
        self.assertEqual(set(m.gray_product('AB','CD')),{('A','C'),('A','D'),('B','C'),('B','D')})
