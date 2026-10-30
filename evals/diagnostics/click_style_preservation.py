"""Post-hoc compatibility probes for Click 8.1.8; not upstream or hidden grading.

Run candidate code only through the Docker runner. Importing this module on the
host loads only the trusted test definitions and limited SGR-state parser.
"""
import re
import unittest


def state_before(text, marker='probe'):
    """Interpret only the basic SGR codes used by these probes, not a terminal."""
    state = {'foreground': None, 'background': None, 'bold': False}
    for match in re.finditer(r'\x1b\[([0-9;]*)m', text[:text.index(marker)]):
        for part in match[1].split(';'):
            code = int(part or '0')
            if code == 0:
                state.update(foreground=None, background=None, bold=False)
            elif code in (1, 22):
                state['bold'] = code == 1
            elif code == 39 or 30 <= code <= 37 or 90 <= code <= 97:
                state['foreground'] = None if code == 39 else code
            elif code == 49 or 40 <= code <= 47 or 100 <= code <= 107:
                state['background'] = None if code == 49 else code
            else:
                raise ValueError('Probe parser does not support this SGR code: ' + str(code))
    return state


class StylePreservation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The sandbox bootstrap verifies that Click comes from the mounted source.
        import click

        cls.click = click

    def test_bold_keeps_existing_foreground(self):
        rendered = self.click.style('\x1b[31mprobe\x1b[0m', bold=True)
        self.assertEqual(state_before(rendered), {'foreground': 31, 'background': None, 'bold': True})

    def test_foreground_keeps_existing_background(self):
        rendered = self.click.style('\x1b[43mprobe\x1b[0m', fg='blue')
        self.assertEqual(state_before(rendered), {'foreground': 34, 'background': 43, 'bold': False})

    def test_background_keeps_existing_foreground(self):
        rendered = self.click.style('\x1b[31mprobe\x1b[0m', bg='blue')
        self.assertEqual(state_before(rendered), {'foreground': 31, 'background': 44, 'bold': False})

    def test_reset_false_keeps_output_open(self):
        rendered = self.click.style('probe', fg='black', reset=False)
        self.assertEqual(rendered, '\x1b[30mprobe')
        self.assertEqual(state_before(rendered)['foreground'], 30)

    def test_nested_open_styles_compose(self):
        inner = self.click.style('probe', fg='red', reset=False)
        rendered = self.click.style(inner, bold=True, reset=False)
        self.assertEqual(state_before(rendered), {'foreground': 31, 'background': None, 'bold': True})
        self.assertFalse(rendered.endswith('\x1b[0m'))

    def test_plain_foreground_background_and_bold(self):
        rendered = self.click.style('probe', fg='blue', bg='yellow', bold=True)
        self.assertEqual(state_before(rendered), {'foreground': 34, 'background': 43, 'bold': True})
        self.assertEqual(self.click.unstyle(rendered), 'probe')
