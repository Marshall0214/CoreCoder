"""Hand-authored development checks derived from public envvar requirements.

Caller choices (flag tokens, variable names, inputs and explicit defaults) are
developer fixtures, not hidden test contents or verified contract labels.
"""

import unittest

import click
from click.testing import CliRunner


class PublicContract(unittest.TestCase):
    def invoke_flag(self, value=None, arguments=()):
        @click.command()
        @click.option('--shade', is_flag=True, flag_value='enabled-shade', default=False,
                      envvar='PUBLIC_SHADE_SWITCH')
        def command(shade):
            click.echo(repr(shade))
        env = {'PUBLIC_SHADE_SWITCH': value} if value is not None else {'PUBLIC_SHADE_SWITCH': None}
        result = CliRunner().invoke(command, list(arguments), env=env)
        self.assertEqual(result.exit_code, 0, result.output)
        return result.output.strip()

    def test_nonactivation_keeps_explicit_default(self):
        for value in ('false', 'off', '0', 'different-token'):
            with self.subTest(value=value):
                self.assertEqual(self.invoke_flag(value), repr(False))

    def test_true_and_exact_values_activate(self):
        for value in ('true', 'yes', 'enabled-shade'):
            with self.subTest(value=value):
                self.assertEqual(self.invoke_flag(value), repr('enabled-shade'))

    def test_whitespace_boolean_is_false(self):
        @click.command()
        @click.option('--switch/--no-switch', default=False, envvar='PUBLIC_BOOL_SWITCH')
        def command(switch):
            click.echo(repr(switch))
        result = CliRunner().invoke(command, [], env={'PUBLIC_BOOL_SWITCH': ' \t '})
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.output.strip(), repr(False))

    def test_explicit_activation_is_preserved(self):
        self.assertEqual(self.invoke_flag(arguments=['--shade']), repr('enabled-shade'))

    def test_normal_argument_conversion_is_preserved(self):
        @click.command()
        @click.argument('count', type=int)
        def command(count):
            click.echo(repr(count + 2))
        result = CliRunner().invoke(command, ['7'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.output.strip(), '9')
