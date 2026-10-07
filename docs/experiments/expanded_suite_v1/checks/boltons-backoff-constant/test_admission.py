import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        from boltons.iterutils import backoff
        self.assertEqual(backoff(3,3,factor=1), [3.0])
        with self.assertRaises(ValueError): backoff(2,9,factor=1)

class Controls(unittest.TestCase):
    def test_preservation(self):
        from boltons.iterutils import backoff
        self.assertEqual(backoff(2,9,count=3,factor=1), [2.0]*3)
        self.assertEqual(backoff(1,4), [1.0,2.0,4.0])
