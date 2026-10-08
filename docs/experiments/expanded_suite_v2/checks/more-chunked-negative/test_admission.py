import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        for source in ([],[1,2]):
            with self.assertRaisesRegex(ValueError,'n must be at least 0'):
                list(m.chunked(source,-1))

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(list(m.chunked([1,2,3],2)),[[1,2],[3]])
        self.assertEqual(list(m.chunked([1,2],None)),[[1,2]])
