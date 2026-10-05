import unittest

from paths import canonical_path


class PublicPathContract(unittest.TestCase):
    def test_single_dot_and_repeated_separators(self):
        self.assertEqual(canonical_path('./a//b.txt'), 'a/b.txt')
        self.assertEqual(canonical_path('a/./b.txt'), 'a/b.txt')

    def test_double_dot_remains_literal(self):
        self.assertEqual(canonical_path('a/../a/b.txt'), 'a/../a/b.txt')
        self.assertEqual(canonical_path('../a.txt'), '../a.txt')

    def test_backslashes_are_logical_separators(self):
        self.assertEqual(canonical_path('.\\a\\..\\b.txt'), 'a/../b.txt')
