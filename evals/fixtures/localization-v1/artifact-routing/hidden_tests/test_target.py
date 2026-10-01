import unittest

from archive import archive_plan
from rules import Rule


class TargetTests(unittest.TestCase):
    def test_windows_and_dot_separators(self):
        paths = ["logs\\app.txt", "./logs//app.txt"]
        self.assertEqual(archive_plan(paths, [Rule("logs/*", "logs")]),
                         {path: "logs" for path in paths})

    def test_priority(self):
        rules = [Rule("*", "default", 0), Rule("logs/*", "logs", 10)]
        self.assertEqual(archive_plan(["logs/app.txt"], rules), {"logs/app.txt": "logs"})

    def test_normalization_and_priority_together(self):
        rules = [Rule("*", "default"), Rule("logs\\*", "logs", 10)]
        self.assertEqual(archive_plan(["./logs\\app.txt"], rules), {"./logs\\app.txt": "logs"})

    def test_case_ties_and_non_mutation(self):
        rules = [Rule("logs/*", "first", 10), Rule("logs/*", "second", 10)]
        original = list(rules)
        self.assertEqual(archive_plan(["logs/a", "Logs/a"], rules), {"logs/a": "first", "Logs/a": "unassigned"})
        self.assertEqual(rules, original)
