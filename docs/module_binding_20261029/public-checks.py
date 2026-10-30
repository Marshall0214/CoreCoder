"""Issue #3887 reporter expectation; not an upstream-approved repair specification.

Only the public issue and version 8.1.8 were used. No reference patch is supplied.
"""
import re
import unittest

import click


def foreground_at(text, needle):
    """Evaluate SGR foreground before the reported text, rather than strip ANSI."""
    color = None
    prefix = text[:text.index(needle)]
    for match in re.finditer(r'\x1b\[([0-9;]*)m', prefix):
        for value in (int(part or '0') for part in match[1].split(';')):
            if value in (0, 39):
                color = None
            elif 30 <= value <= 37 or 90 <= value <= 97:
                color = value
    return color


class Reproduce(unittest.TestCase):
    def test_explicit_blue_overrides_precolored_input(self):
        colored = '\033[0;31mThis should be blue\033[0m'
        rendered = click.style(colored, fg='blue')
        self.assertEqual(foreground_at(rendered, 'This should be blue'), 34)


class Preserve(unittest.TestCase):
    def test_plain_input_can_be_colored(self):
        self.assertEqual(foreground_at(click.style('plain', fg='blue'), 'plain'), 34)

    def test_unstyle_preserves_visible_text(self):
        self.assertEqual(click.unstyle(click.style('plain', fg='red', bold=True)), 'plain')

    def test_existing_color_without_override_is_retained(self):
        red = '\033[31mred\033[0m'
        self.assertEqual(foreground_at(click.style(red), 'red'), 31)
