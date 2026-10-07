import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        from boltons.iterutils import chunked
        self.assertEqual(chunked(b'abcdefg',3), [b'abc',b'def',b'g'])

class Controls(unittest.TestCase):
    def test_preservation(self):
        from boltons.iterutils import chunked
        self.assertEqual(chunked('abcdefg',3), ['abc','def','g'])
        self.assertEqual(chunked([1,2,3],2), [[1,2],[3]])
