import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        from toolz import interpose
        self.assertEqual(list(interpose('-', [])), [])
        self.assertEqual(list(interpose('-', iter(()))), [])

class Controls(unittest.TestCase):
    def test_preservation(self):
        from toolz import interpose
        self.assertEqual(list(interpose('-', [2,4])), [2,'-',4])
        self.assertEqual(list(interpose('-', [7])), [7])
