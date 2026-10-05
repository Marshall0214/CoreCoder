import unittest

import click
from click.testing import CliRunner


def command(default_first):
    options = [
        click.Option(['--quick', 'mode'], flag_value='quick'),
        click.Option(['--safe', 'mode'], flag_value='safe', default=True),
    ]
    if default_first:
        options.reverse()
    return click.Command('choose', params=options, callback=lambda mode: mode)


class Target(unittest.TestCase):
    def test_shared_default_is_declaration_order_independent(self):
        for default_first in (False, True):
            with self.subTest(default_first=default_first):
                result = CliRunner().invoke(command(default_first), standalone_mode=False)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.return_value, 'safe')


class Controls(unittest.TestCase):
    def test_explicit_flags_override_shared_default(self):
        for default_first in (False, True):
            for flag, expected in (('--quick', 'quick'), ('--safe', 'safe')):
                with self.subTest(default_first=default_first, flag=flag):
                    result = CliRunner().invoke(
                        command(default_first), [flag], standalone_mode=False
                    )
                    self.assertEqual(result.exit_code, 0)
                    self.assertEqual(result.return_value, expected)
