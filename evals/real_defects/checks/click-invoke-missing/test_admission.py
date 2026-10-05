import unittest

import click
from click.testing import CliRunner


def invoke(options, supplied=None):
    @click.command()
    @click.option('--label', **options)
    def recipient(label):
        return label

    @click.command()
    @click.pass_context
    def caller(ctx):
        return ctx.invoke(recipient, **(supplied or {}))

    return CliRunner().invoke(caller, standalone_mode=False)


class Target(unittest.TestCase):
    def test_missing_optional_value_is_none(self):
        for options in ({'type': click.STRING}, {'required': False}):
            with self.subTest(options=options):
                result = invoke(options)
                self.assertEqual(result.exit_code, 0)
                self.assertIsNone(result.return_value)


class Controls(unittest.TestCase):
    def test_default_cast_and_explicit_value(self):
        for options, supplied, expected in (
            ({'type': click.INT, 'default': '23'}, None, 23),
            ({'multiple': True}, None, ()),
            ({'type': click.STRING}, {'label': 'manual'}, 'manual'),
            ({'default': None}, None, None),
        ):
            with self.subTest(options=options, supplied=supplied):
                result = invoke(options, supplied)
                self.assertEqual(result.exit_code, 0)
                self.assertEqual(result.return_value, expected)
