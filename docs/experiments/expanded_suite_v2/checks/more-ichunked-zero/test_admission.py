import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        source=iter([4,5,6])
        self.assertEqual(list(m.ichunked(source,0)),[])
        self.assertEqual(list(source),[4,5,6])
        with self.assertRaisesRegex(ValueError,'n must be at least 0'):
            list(m.ichunked([1],-1))

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual([list(c) for c in m.ichunked([1,2,3],2)],[[1,2],[3]])
