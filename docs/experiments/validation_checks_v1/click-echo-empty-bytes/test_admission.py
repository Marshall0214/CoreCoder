"""Independent unittest reproductions of Click issue 3487 / PR 3493."""

import io
import unittest

import click


class Target(unittest.TestCase):
    def test_empty_binary_messages_write_binary_newline(self):
        for message in (b'', bytearray()):
            with self.subTest(type=type(message).__name__):
                stream = io.BytesIO()
                try:
                    click.echo(message, stream)
                except TypeError as exc:
                    self.fail(f'Empty binary messages must not raise TypeError: {exc}')
                self.assertEqual(stream.getvalue(), b'\n')


class Controls(unittest.TestCase):
    def test_nonempty_binary_and_no_newline(self):
        for message, nl, expected in ((b'value', True, b'value\n'),
                                      (bytearray(b'value'), True, b'value\n'),
                                      (b'', False, b''), (b'value', False, b'value')):
            with self.subTest(message=message, nl=nl):
                stream = io.BytesIO()
                click.echo(message, stream, nl=nl)
                self.assertEqual(stream.getvalue(), expected)

    def test_text_none_and_object_messages(self):
        for message, nl, expected in (('value', True, 'value\n'), (None, True, '\n'),
                                      (None, False, ''), (17, True, '17\n')):
            with self.subTest(message=message, nl=nl):
                stream = io.StringIO()
                click.echo(message, stream, nl=nl)
                self.assertEqual(stream.getvalue(), expected)
