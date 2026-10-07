"""Four hand-authored calibration tasks; grading and references stay in the parent."""

CASES = [
    {'id': 'unique-falsey',
     'description': 'resolve must use fallback only when value is None. Preserve 0, False, empty string and other values.',
     'source': 'def resolve(value, fallback):\n    return value or fallback\n',
     'reference': [('return value or fallback', 'return fallback if value is None else value')],
     'checks': """import unittest
from app import resolve
class Checks(unittest.TestCase):
    def test_none(self):
        self.assertEqual(resolve(None, 'fallback'), 'fallback')
    def test_falsey_and_values(self):
        for value in (0, False, '', [], 'value'):
            with self.subTest(value=value):
                self.assertEqual(resolve(value, 'fallback'), value)
"""},
    {'id': 'preserve-methods',
     'description': 'Formatter.render must return prefix alone for empty value, and prefix + one space + value otherwise. Preserve width and existing method definitions; change the existing render body rather than adding another render.',
     'source': "class Formatter:\n    def width(self):\n        return 80\n    def render(self, prefix, value):\n        return prefix + ' ' + value\n",
     'reference': [("return prefix + ' ' + value", "return prefix if value == '' else prefix + ' ' + value")],
     'checks': """import unittest
from app import Formatter
class Checks(unittest.TestCase):
    def test_empty_and_nonempty(self):
        formatter = Formatter()
        self.assertEqual(formatter.render('Run:', ''), 'Run:')
        self.assertEqual(formatter.render('Run:', 'demo'), 'Run: demo')
    def test_preserve_width(self):
        self.assertEqual(Formatter().width(), 80)
"""},
    {'id': 'annotation-import',
     'description': 'The module must load. normalize accepts strings and bytes and returns them unchanged. Its annotation must use the existing _str_bytes alias, not a nonexistent attribute on typing. Preserve other definitions.',
     'source': "import typing as _t\n_str_bytes = _t.Union[str, bytes]\ndef normalize(value: _t.str_bytes) -> _str_bytes:\n    return value\n",
     'reference': [('_t.str_bytes', '_str_bytes')],
     'checks': """import unittest
from app import normalize
class Checks(unittest.TestCase):
    def test_strings_and_bytes(self):
        for value in ('text', b'text', '', b''):
            self.assertEqual(normalize(value), value)
    def test_annotation(self):
        from app import _str_bytes
        self.assertEqual(normalize.__annotations__['value'], _str_bytes)
"""},
    {'id': 'default-none-override',
     'description': 'Envelope.effective must preserve these relations: omitted constructor salt and omitted/None method override use envelope-default; explicit constructor None with omitted/None method override uses signer-default; explicit constructor salt including empty string is preserved; explicit method override including empty string overrides any instance salt. Preserve existing definitions.',
     'source': "class Envelope:\n    def __init__(self, salt='envelope-default'):\n        self.salt = salt\n    def effective(self, override=None):\n        return override or self.salt\n",
     'reference': [('return override or self.salt', "salt = self.salt if override is None else override\n        return 'signer-default' if salt is None else salt")],
     'checks': """import unittest
from app import Envelope
class Checks(unittest.TestCase):
    def test_constructor_cases(self):
        self.assertEqual(Envelope().effective(), 'envelope-default')
        self.assertEqual(Envelope().effective(None), 'envelope-default')
        self.assertEqual(Envelope(None).effective(), 'signer-default')
        self.assertEqual(Envelope(None).effective(None), 'signer-default')
        self.assertEqual(Envelope('').effective(), '')
        self.assertEqual(Envelope('custom').effective(), 'custom')
    def test_method_overrides(self):
        for envelope in (Envelope(), Envelope(None), Envelope('custom'), Envelope('')):
            for override in ('', 'override'):
                self.assertEqual(envelope.effective(override), override)
"""},
]
