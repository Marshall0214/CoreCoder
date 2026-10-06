"""Independent unittest reproductions of Click PR 3677."""

import io
import unittest

import click


class Target(unittest.TestCase):
    def test_palette_zero_foreground_and_background(self):
        for parameter, code in (('fg', 38), ('bg', 48)):
            with self.subTest(parameter=parameter):
                self.assertEqual(click.style('value', **{parameter: 0}), f'\x1b[{code};5;0mvalue\x1b[0m')

    def test_secho_preserves_palette_zero(self):
        for parameter, code in (('fg', 38), ('bg', 48)):
            with self.subTest(parameter=parameter):
                stream = io.StringIO()
                click.secho('value', file=stream, color=True, **{parameter: 0})
                self.assertEqual(stream.getvalue(), f'\x1b[{code};5;0mvalue\x1b[0m\n')

    def test_invalid_colors_raise_value_error(self):
        invalid = ('missing-color', '', True, False, -1, 256, 0.0,
                   (), (1, 2), (1, 2, 3, 4), ('1', '2', '3'), (True, 0, 0), (-1, 0, 0), (0, 256, 0))
        for parameter in ('fg', 'bg'):
            for color in invalid:
                with self.subTest(parameter=parameter, color=color):
                    try:
                        click.style('value', **{parameter: color})
                    except ValueError as exc:
                        self.assertIn('Unknown color', str(exc))
                    except (TypeError, KeyError) as exc:
                        self.fail(f'Invalid color must raise ValueError, got {type(exc).__name__}')
                    else:
                        self.fail('Invalid color was accepted')


class Controls(unittest.TestCase):
    def test_named_palette_and_rgb_colors(self):
        for kwargs, prefix in (({'fg': 'red'}, '\x1b[31m'), ({'bg': 255}, '\x1b[48;5;255m'),
                               ({'fg': (1, 2, 3)}, '\x1b[38;2;1;2;3m'),
                               ({'bg': [3, 2, 1]}, '\x1b[48;2;3;2;1m')):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(click.style('value', **kwargs), prefix + 'value\x1b[0m')

    def test_reset_and_plain_secho(self):
        self.assertEqual(click.style('value', fg='red', reset=False), '\x1b[31mvalue')
        stream = io.StringIO()
        click.secho('value', file=stream, color=False, fg='red')
        self.assertEqual(stream.getvalue(), 'value\n')
