"""Independent unittest reproductions of Click issue 3360 / PR 3434."""

import unittest

import click
from click.testing import CliRunner


class Target(unittest.TestCase):
    def test_empty_args_preserve_prefix_and_program(self):
        for width, prefix, expected in ((80, None, 'Usage: program\n'),
                                        (80, 'Run: ', 'Run: program\n'),
                                        (18, None, 'Usage: program\n')):
            with self.subTest(width=width, prefix=prefix):
                formatter = click.HelpFormatter(width=width)
                formatter.write_usage('program', '', prefix=prefix)
                self.assertEqual(formatter.getvalue(), expected)

    def test_parameterless_command_keeps_usage_line(self):
        for metavar in ('', None):
            with self.subTest(metavar=metavar):
                result = CliRunner().invoke(click.Command('sample', options_metavar=metavar), ['--help'])
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.output.splitlines()[0], 'Usage: sample')


class Controls(unittest.TestCase):
    def test_nonempty_args_and_custom_prefix(self):
        for prefix, expected in ((None, 'Usage: sample [OPTIONS]\n'), ('Run: ', 'Run: sample [OPTIONS]\n')):
            with self.subTest(prefix=prefix):
                formatter = click.HelpFormatter(width=80)
                formatter.write_usage('sample', '[OPTIONS]', prefix=prefix)
                self.assertEqual(formatter.getvalue(), expected)

    def test_normal_command_help(self):
        result = CliRunner().invoke(click.Command('sample'), ['--help'])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output.splitlines()[0], 'Usage: sample [OPTIONS]')
