"""Developer examples from the public usage requirements and original API defaults."""

import unittest

import click


class PublicContract(unittest.TestCase):
    def render(self, args='', width=80, prefix=None):
        formatter = click.HelpFormatter(width=width)
        formatter.write_usage('demo', args, prefix=prefix)
        return formatter.getvalue()

    def test_empty_usage_wide(self):
        self.assertEqual(self.render(), 'Usage: demo\n')

    def test_empty_usage_narrow_custom_prefix(self):
        self.assertEqual(self.render(width=18, prefix='Execute: '), 'Execute: demo\n')

    def test_nonempty_arguments_and_custom_prefix(self):
        self.assertEqual(self.render('--mode fast', prefix='Execute: '), 'Execute: demo --mode fast\n')

    def test_command_empty_and_none_metavar(self):
        for metavar in ('', None):
            with self.subTest(metavar=metavar):
                command = click.Command('demo', params=[], options_metavar=metavar, add_help_option=False)
                with click.Context(command, info_name='demo', terminal_width=80) as context:
                    self.assertEqual(command.get_usage(context), 'Usage: demo')
