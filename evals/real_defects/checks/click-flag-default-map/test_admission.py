import unittest

import click
from click.testing import CliRunner


def command():
    @click.command()
    @click.option('--enabled/--disabled', default=False, show_default=True)
    def cli(enabled):
        click.echo(str(enabled))
    return cli


class Target(unittest.TestCase):
    def test_help_uses_effective_default(self):
        result = CliRunner().invoke(command(), ['--help'], default_map={'enabled': True})
        self.assertEqual(result.exit_code, 0)
        self.assertIn('default: enabled', result.output)
        self.assertNotIn('default: disabled', result.output)


class Controls(unittest.TestCase):
    def test_execution_uses_effective_default(self):
        result = CliRunner().invoke(command(), [], default_map={'enabled': True})
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output.strip(), 'True')
