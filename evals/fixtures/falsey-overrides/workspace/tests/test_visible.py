import unittest
from service import effective_options


class RegressionTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(effective_options({})["max_jobs"], 3)

    def test_nonzero_override(self):
        self.assertEqual(effective_options({"max_jobs": 8})["max_jobs"], 8)
