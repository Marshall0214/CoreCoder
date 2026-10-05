import unittest

import click
from click.testing import CliRunner


def command():
    @click.command()
    @click.option('--style', is_flag=True, type=str, flag_value='bright', envvar='ADMISSION_STYLE')
    def cli(style):
        click.echo(repr(style))

    return cli


class Target(unittest.TestCase):
    def test_false_environment_does_not_activate(self):
        for value in ('false', '0', ' off '):
            with self.subTest(value=value):
                result = CliRunner().invoke(command(), env={'ADMISSION_STYLE': value})
                self.assertEqual(result.exit_code, 0, repr(result.exception))
                self.assertEqual(result.output.strip(), repr('False'))

    def test_nonmatching_environment_does_not_activate(self):
        for value in ('BRIGHT', ' bright ', 'unrelated'):
            with self.subTest(value=value):
                result = CliRunner().invoke(command(), env={'ADMISSION_STYLE': value})
                self.assertEqual(result.exit_code, 0, repr(result.exception))
                self.assertEqual(result.output.strip(), repr('False'))

    def test_boolean_whitespace_is_false(self):
        @click.command()
        @click.option('--enabled/--disabled', envvar='ADMISSION_BOOL')
        def cli(enabled):
            click.echo(repr(enabled))

        result = CliRunner().invoke(cli, env={'ADMISSION_BOOL': '   '})
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output.strip(), 'False')


class Controls(unittest.TestCase):
    def test_explicit_activation(self):
        result = CliRunner().invoke(command(), ['--style'], env={'ADMISSION_STYLE': None})
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output.strip(), repr('bright'))

    def test_true_and_exact_environment_activation(self):
        for value in ('yes', 'bright'):
            with self.subTest(value=value):
                result = CliRunner().invoke(command(), env={'ADMISSION_STYLE': value})
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.output.strip(), repr('bright'))

    def test_normal_integer_argument(self):
        @click.command()
        @click.argument('count', type=int)
        def cli(count):
            click.echo(count + 1)

        result = CliRunner().invoke(cli, ['4'])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output.strip(), '5')
