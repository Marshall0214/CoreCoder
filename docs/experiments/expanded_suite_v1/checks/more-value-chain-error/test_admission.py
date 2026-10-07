import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        import more_itertools as mi
        def broken():
            yield 3
            raise TypeError('inside iterator')
        it=mi.value_chain(broken(),7)
        self.assertEqual(next(it),3)
        with self.assertRaises(TypeError): next(it)

class Controls(unittest.TestCase):
    def test_preservation(self):
        import more_itertools as mi
        class Scalar:
            def __iter__(self): raise TypeError('not iterable')
        x=Scalar()
        self.assertEqual(list(mi.value_chain(1,x,[2,3])),[1,x,2,3])
