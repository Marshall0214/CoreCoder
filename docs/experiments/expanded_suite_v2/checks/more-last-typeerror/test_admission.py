import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        class Broken:
            def __reversed__(self): raise TypeError('broken reverse')
        with self.assertRaisesRegex(TypeError,'broken reverse'):
            m.last(Broken(),default=9)

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(m.last([1,2]),2)
        self.assertEqual(m.last([],default=9),9)
