import unittest

import click
from click.testing import CliRunner


class Target(unittest.TestCase):
    def test_help_before_eager_callback(self):
        called = []

        def eager(ctx, param, value):
            if value:
                called.append(value)
                ctx.exit()

        @click.command(context_settings={'help_option_names': ['--assist']})
        @click.option('--interrupt', is_flag=True, is_eager=True, expose_value=False, callback=eager)
        def command():
            pass

        result = CliRunner().invoke(command, ['--assist', '--interrupt'])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('Usage:', result.output)
        self.assertEqual(called, [])


class Controls(unittest.TestCase):
    def test_eager_callback_before_help(self):
        called = []

        def eager(ctx, param, value):
            if value:
                called.append(value)
                ctx.exit()

        @click.command(context_settings={'help_option_names': ['--assist']})
        @click.option('--interrupt', is_flag=True, is_eager=True, expose_value=False, callback=eager)
        def command():
            pass

        result = CliRunner().invoke(command, ['--interrupt', '--assist'])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(called, [True])
