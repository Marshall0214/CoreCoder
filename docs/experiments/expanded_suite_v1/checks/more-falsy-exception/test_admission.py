import unittest

class Target(unittest.TestCase):
    def test_contract(self):
        import more_itertools as mi
        class Falsy(Exception):
            def __bool__(self): return False
        for operation in (lambda:mi.one([],too_short=Falsy()),lambda:mi.one([1,2],too_long=Falsy()),lambda:mi.only([1,2],too_long=Falsy())):
            with self.assertRaises(Falsy): operation()
        class NoRepr:
            def __repr__(self): raise RuntimeError('repr forbidden')
        with self.assertRaises(OverflowError): mi.one([NoRepr(),NoRepr()],too_long=OverflowError)

class Controls(unittest.TestCase):
    def test_preservation(self):
        import more_itertools as mi
        self.assertEqual(mi.one([8]),8)
        self.assertEqual(mi.only([],default=9),9)
        with self.assertRaises(ValueError): mi.one([])
