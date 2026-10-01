import unittest
from service import effective_options


class TargetTests(unittest.TestCase):
    def test_falsey_values_are_explicit(self):
        value = effective_options({"max_jobs": 0, "enabled": False, "label": ""})
        self.assertEqual(value["max_jobs"], 0)
        self.assertIs(value["enabled"], False)
        self.assertEqual(value["label"], "")

    def test_none_keeps_defaults(self):
        self.assertEqual(effective_options({"max_jobs": None})["max_jobs"], 3)
