"""Versioned public contract: explicit false defaults must survive conversion."""

CODE = '''"""Public contract v1, derived from activation rules and declared default/type."""
import unittest
import click
from click.testing import CliRunner

def invoke(value, args=()):
    @click.command()
    @click.option('--feature', is_flag=True, type=str, default=False,
                  flag_value='enabled-value', envvar='PUBLIC_FLAG_CONTRACT')
    def cli(feature):
        click.echo(repr(feature))
    result = CliRunner().invoke(cli, list(args), env={'PUBLIC_FLAG_CONTRACT': value})
    if result.exit_code:
        raise AssertionError(repr(result.exception))
    return result.output.strip()

class Reproduce(unittest.TestCase):
    def test_deactivation_preserves_declared_false_after_string_conversion(self):
        # Expected value comes from this public declaration, never a hidden grader.
        for value in ('0', 'off', 'n', 'not-enabled', 'ENABLED-VALUE', ' enabled-value '):
            with self.subTest(value=value):
                self.assertEqual(invoke(value), repr(str(False)))

    def test_boolean_blank_is_false(self):
        @click.command()
        @click.option('--active/--inactive', envvar='PUBLIC_BOOL_CONTRACT')
        def cli(active):
            click.echo(repr(active))
        result = CliRunner().invoke(cli, env={'PUBLIC_BOOL_CONTRACT': '\\t  '})
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output.strip(), repr(False))

class Preserve(unittest.TestCase):
    def test_activation_and_command_line_precedence(self):
        for value in ('yes', 'ON', 'enabled-value'):
            with self.subTest(value=value):
                self.assertEqual(invoke(value), repr('enabled-value'))
        self.assertEqual(invoke('off', ('--feature',)), repr('enabled-value'))

    def test_nonflag_environment_keeps_ordinary_conversion(self):
        @click.command()
        @click.option('--quantity', type=int, envvar='PUBLIC_INT_CONTRACT')
        def cli(quantity):
            click.echo(quantity + 2)
        result = CliRunner().invoke(cli, env={'PUBLIC_INT_CONTRACT': '5'})
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output.strip(), '7')
'''


def write_harness(path):
    path.mkdir(parents=True, exist_ok=False)
    (path / 'test_admission.py').write_text(CODE, encoding='utf-8')
    return path
