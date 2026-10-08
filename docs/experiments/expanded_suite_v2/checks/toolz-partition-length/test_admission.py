import unittest

import toolz as m


class Target(unittest.TestCase):
    def test_contract(self):
        class Bad(list):
            def __len__(self): return super().__len__()+1
        with self.assertRaises(LookupError):
            list(m.partition_all(5,Bad([1,2])))

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(list(m.partition_all(2,[1,2,3])),[(1,2),(3,)])
        self.assertEqual(list(m.partition_all(2,iter([1,2,3]))),[(1,2),(3,)])
