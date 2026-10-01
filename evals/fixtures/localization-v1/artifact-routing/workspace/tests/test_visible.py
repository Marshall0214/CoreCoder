import unittest

from archive import archive_plan
from rules import Rule
from preview import preview_first
from notifications import first_channel


class RegressionTests(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(archive_plan(["logs/app.txt", "readme.md"], [Rule("logs/*", "logs")]),
                         {"logs/app.txt": "logs", "readme.md": "unassigned"})

    def test_preview_keeps_first_rule(self):
        rules = [Rule("*", "first", 0), Rule("*", "second", 10)]
        self.assertEqual(preview_first("x", rules), "first")
        self.assertEqual(first_channel(["mail", "sms"]), "mail")
