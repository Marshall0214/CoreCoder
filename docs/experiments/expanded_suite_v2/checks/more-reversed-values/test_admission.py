import unittest

import more_itertools as m


class Target(unittest.TestCase):
    def test_contract(self):
        for args in ((0.0,1.0,0.1),(1.0,0.0,-0.1)):
            r=m.numeric_range(*args)
            self.assertEqual(list(reversed(r)),list(r)[::-1])
        from datetime import datetime, timedelta
        r=m.numeric_range(datetime.min,datetime.min+timedelta(days=2),timedelta(days=1))  # noqa: DTZ901 - historical naive datetime contract
        self.assertEqual(list(reversed(r)),list(r)[::-1])

class Controls(unittest.TestCase):
    def test_preservation(self):
        self.assertEqual(list(reversed(m.numeric_range(4))),[3,2,1,0])
        self.assertEqual(list(reversed(m.numeric_range(0))),[])
