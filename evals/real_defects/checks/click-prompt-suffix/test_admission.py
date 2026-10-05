import unittest

import click
from click.testing import CliRunner


def capture(kind, suffix):
    @click.command()
    def command():
        if kind == 'prompt':
            value = click.prompt('Account', prompt_suffix=suffix)
            click.echo(f'value={value}')
        else:
            value = click.confirm('Proceed', prompt_suffix=suffix, show_default=False)
            click.echo(f'value={value}')

    return CliRunner().invoke(command, input='alice\n' if kind == 'prompt' else 'yes\n')


class Target(unittest.TestCase):
    def test_empty_suffix_preserves_exact_prompt(self):
        for kind, expected in (
            ('prompt', 'Accountalice\nvalue=alice\n'),
            ('confirm', 'Proceedyes\nvalue=True\n'),
        ):
            with self.subTest(kind=kind):
                result = capture(kind, '')
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.output, expected)


class Controls(unittest.TestCase):
    def test_normal_suffix_and_return_value(self):
        for kind, expected in (
            ('prompt', 'Account: alice\nvalue=alice\n'),
            ('confirm', 'Proceed: yes\nvalue=True\n'),
        ):
            with self.subTest(kind=kind):
                result = capture(kind, ': ')
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.output, expected)
