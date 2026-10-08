import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        class Once:
            def __init__(self): self.opened=False
            def __iter__(self):
                if self.opened: raise RuntimeError('opened twice')
                self.opened=True
                return iter([1,2])
        for strict in (False,True):
            self.assertEqual(list(m.zip_broadcast('tag',Once(),strict=strict)),[('tag',1),('tag',2)])

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(list(m.zip_broadcast(9,[1,2])),[(9,1),(9,2)])
