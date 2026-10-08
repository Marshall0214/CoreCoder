"""Developer-authored examples from public descriptions; no private grader imports.

These are development checks, not unseen tests or automatically generated tests.
The author has seen earlier experiment outcomes. References certify the checks
after authoring; they are never repair-model input.
"""
import textwrap

# (imports/helpers, reproduction, preservation), each with independent examples.
CASES = {
    'click-usage-empty': (
        'import click',
        "f = click.HelpFormatter()\nf.write_usage('sample', '')\nself.assertEqual(f.getvalue(), 'Usage: sample\\n')",
        "f = click.HelpFormatter()\nf.write_usage('sample', '--verbose', prefix='Run: ')\nself.assertEqual(f.getvalue(), 'Run: sample --verbose\\n')"),
    'click-echo-empty-bytes': (
        'import click\nimport io',
        "for value in (b'', bytearray()):\n    stream = io.BytesIO()\n    click.echo(value, file=stream)\n    self.assertEqual(stream.getvalue(), b'\\n')",
        "stream = io.BytesIO()\nclick.echo(b'abc', file=stream, nl=False)\nself.assertEqual(stream.getvalue(), b'abc')\ntext = io.StringIO()\nclick.echo(17, file=text)\nself.assertEqual(text.getvalue(), '17\\n')"),
    'click-style-color-validation': (
        'import click',
        "self.assertIn('38;5;0', click.style('x', fg=0))\nself.assertIn('48;5;0', click.style('x', bg=0))\nfor value in (True, -1, 256, (1, 2), (1, False, 3), (1, 2, 256), 'unknown-public-color'):\n    with self.assertRaises(ValueError):\n        click.style('x', fg=value)",
        "self.assertIn('38;5;7', click.style('x', fg=7))\nself.assertIn('38;2;1;2;3', click.style('x', fg=(1, 2, 3)))\nself.assertIn('31', click.style('x', fg='red'))\nself.assertEqual(click.unstyle(click.style('x', fg='blue')), 'x')"),
    'itsdangerous-none-salt': (
        'from itsdangerous import Serializer, Signer, BadSignature',
        "self.assertEqual(Signer('public-key', salt=None).sign(b'msg'), Signer('public-key').sign(b'msg'))\ns = Serializer('public-key', salt=None)\nvalue = {'public': 7}\npayload = s.dump_payload(value)\npayload = payload.encode() if isinstance(payload, str) else payload\ntoken = s.dumps(value)\ntoken = token.encode() if isinstance(token, str) else token\nself.assertEqual(token, Signer('public-key').sign(payload))\nself.assertEqual(s.loads(token), value)",
        "self.assertEqual(Serializer('public-key').dumps(7), Serializer('public-key', salt=b'itsdangerous').dumps(7))\nself.assertEqual(Serializer('public-key', salt='custom').dumps(7), Serializer('public-key', salt=b'custom').dumps(7))\ns = Serializer('public-key', salt='custom')\nwith self.assertRaises(BadSignature):\n    Serializer('public-key', salt='other').loads(s.dumps(7))\nwith self.assertRaises(BadSignature):\n    s.loads(s.dumps(7) + '-tampered')"),
    'itsdangerous-future-age': (
        '''from itsdangerous import TimestampSigner, SignatureExpired
class Clock(TimestampSigner):
    now = 1000
    def get_timestamp(self):
        return self.now''',
        "s = Clock('public-key')\ns.now = 1001\ntoken = s.sign(b'future')\ns.now = 1000\nwith self.assertRaises(SignatureExpired) as caught:\n    s.unsign(token, max_age=10)\nself.assertEqual(caught.exception.payload, b'future')\nself.assertFalse(s.validate(token, max_age=10))",
        "s = Clock('public-key')\ntoken = s.sign(b'past')\nfor now in (1000, 1010):\n    s.now = now\n    self.assertEqual(s.unsign(token, max_age=10), b'past')\ns.now = 1011\nwith self.assertRaises(SignatureExpired):\n    s.unsign(token, max_age=10)\ns.now = 999\nself.assertEqual(s.unsign(token), b'past')"),
    'itsdangerous-malformed-time': (
        '''from itsdangerous import TimestampSigner, BadTimeSignature
from itsdangerous.encoding import base64_encode, int_to_bytes''',
        "s = TimestampSigner('public-key')\ntoken = b'public.' + base64_encode(int_to_bytes(2**40)) + b'.invalid'\nwith self.assertRaises(BadTimeSignature) as caught:\n    s.unsign(token)\nself.assertEqual(caught.exception.payload, b'public')\nself.assertIsNone(caught.exception.date_signed)\nself.assertFalse(s.validate(token))",
        "s = TimestampSigner('public-key')\nself.assertEqual(s.unsign(s.sign(b'public'), max_age=60), b'public')\nwith self.assertRaises(BadTimeSignature):\n    s.unsign(s.sign(b'public') + b'invalid')"),
    'click-help-eagerness': (
        '''import click
from click.testing import CliRunner
def command(events):
    def eager(ctx, param, value):
        if value:
            events.append('eager')
    @click.command(context_settings={'help_option_names': ['--assist']})
    @click.option('--early', is_flag=True, is_eager=True, callback=eager, expose_value=False)
    def cli():
        click.echo('body')
    return cli''',
        "events = []\nr = CliRunner().invoke(command(events), ['--assist', '--early'])\nself.assertEqual(r.exit_code, 0)\nself.assertIn('Usage:', r.output)\nself.assertEqual(events, [])",
        "events = []\nr = CliRunner().invoke(command(events), ['--early'])\nself.assertEqual(r.exit_code, 0)\nself.assertEqual(events, ['eager'])\nself.assertIn('body', r.output)"),
    'click-flag-default-map': (
        '''import click
from click.testing import CliRunner
@click.command()
@click.option('--fast/--slow', default=True, show_default=True)
def cli(fast):
    click.echo(str(fast))''',
        "r = CliRunner().invoke(cli, ['--help'], default_map={'fast': False})\nself.assertEqual(r.exit_code, 0)\nself.assertIn('[default: slow]', r.output)\nself.assertEqual(CliRunner().invoke(cli, [], default_map={'fast': False}).output.strip(), 'False')",
        "self.assertEqual(CliRunner().invoke(cli, []).output.strip(), 'True')\nself.assertEqual(CliRunner().invoke(cli, ['--slow']).output.strip(), 'False')"),
    'click-resource-exception': (
        '''import click
class Resource:
    def __init__(self, suppress=False):
        self.suppress = suppress
        self.seen = None
    def __enter__(self):
        return self
    def __exit__(self, kind, value, trace):
        self.seen = (kind, value, trace)
        return self.suppress''',
        "r = Resource(True)\nwith click.Context(click.Command('public')) as ctx:\n    ctx.with_resource(r)\n    raise ValueError('public-error')\nself.assertIs(r.seen[0], ValueError)\nself.assertEqual(str(r.seen[1]), 'public-error')\nself.assertIsNotNone(r.seen[2])",
        "r = Resource()\nwith click.Context(click.Command('public')) as ctx:\n    self.assertIs(ctx.with_resource(r), r)\nself.assertEqual(r.seen, (None, None, None))"),
    'click-flag-envvar': (
        '''import click
from click.testing import CliRunner
@click.command()
@click.option('--upper', 'mode', flag_value='UPPER', envvar='PUBLIC_MODE')
def cli(mode):
    click.echo(repr(mode))''',
        "for value in ('false', '0', 'no'):\n    r = CliRunner().invoke(cli, [], env={'PUBLIC_MODE': value})\n    self.assertEqual(r.exit_code, 0)\n    self.assertNotEqual(r.output.strip(), repr('UPPER'))",
        "for value in ('true', '1', 'UPPER'):\n    self.assertEqual(CliRunner().invoke(cli, [], env={'PUBLIC_MODE': value}).output.strip(), repr('UPPER'))\nself.assertEqual(CliRunner().invoke(cli, ['--upper'], env={'PUBLIC_MODE': 'false'}).output.strip(), repr('UPPER'))"),
    'click-prompt-suffix': (
        'import click\nfrom click.testing import CliRunner',
        "@click.command()\ndef cli():\n    click.prompt('Count', prompt_suffix='', type=int)\nr = CliRunner().invoke(cli, input='5\\n')\nself.assertEqual(r.exit_code, 0)\nself.assertTrue(r.output.startswith('Count5\\n'), repr(r.output))",
        "@click.command()\ndef cli():\n    click.echo(click.prompt('Count', type=int))\nr = CliRunner().invoke(cli, input='5\\n')\nself.assertEqual(r.exit_code, 0)\nself.assertIn('Count: 5', r.output)\nself.assertTrue(r.output.endswith('5\\n'))"),
    'click-invoke-missing': (
        '''import click
@click.command()
@click.option('--value', type=int)
def cli(value):
    return value''',
        "with click.Context(click.Command('public')) as ctx:\n    self.assertIsNone(ctx.invoke(cli))",
        "with click.Context(click.Command('public')) as ctx:\n    self.assertEqual(ctx.invoke(cli, value=8), 8)"),
    'click-shared-default': (
        '''import click
from click.testing import CliRunner
def command(reverse):
    def callback(mode):
        click.echo(mode)
    options = [click.Option(['--alpha', 'mode'], flag_value='alpha', default=True),
               click.Option(['--beta', 'mode'], flag_value='beta')]
    return click.Command('public', callback=callback, params=options[::-1] if reverse else options)''',
        "for reverse in (False, True):\n    r = CliRunner().invoke(command(reverse), [])\n    self.assertEqual(r.exit_code, 0)\n    self.assertEqual(r.output.strip(), 'alpha')",
        "for reverse in (False, True):\n    self.assertEqual(CliRunner().invoke(command(reverse), ['--beta']).output.strip(), 'beta')"),
    'toolz-interpose-empty': ('from toolz import interpose',
        'self.assertEqual(list(interpose(0, [])), [])',
        'self.assertEqual(list(interpose(0, [3, 4, 5])), [3, 0, 4, 0, 5])'),
    'toolz-accumulate-empty': ('from toolz import accumulate\nfrom operator import add',
        'self.assertEqual(list(accumulate(add, [])), [])\nself.assertEqual(list(accumulate(add, [], initial=10)), [10])',
        'self.assertEqual(list(accumulate(add, [2, 3, 4])), [2, 5, 9])'),
    'toolz-join-unmatched': ('from toolz import join',
        "self.assertEqual(list(join(lambda x: x, [2], lambda x: x, [3], right_default='absent')), [(2, 'absent')])",
        'self.assertEqual(list(join(lambda x: x, [2, 3], lambda x: x, [3, 4])), [(3, 3)])'),
    'toolz-getter-empty': ('from toolz.itertoolz import getter',
        "self.assertEqual(getter([])([8, 9]), ())\nself.assertEqual(getter([])(None), ())",
        'self.assertEqual(getter(1)([8, 9]), 9)\nself.assertEqual(getter([1])([8, 9]), (9,))'),
    'boltons-backoff-constant': ('from boltons.iterutils import backoff, backoff_iter',
        'self.assertEqual(backoff(start=4, stop=4, factor=1), [4])\nwith self.assertRaises(ValueError):\n    list(backoff_iter(start=2, stop=4, factor=1))',
        'self.assertEqual(backoff(start=4, stop=4, factor=1, count=3), [4, 4, 4])\nself.assertEqual(backoff(start=1, stop=4, factor=2, count=3), [1, 2, 4])'),
    'boltons-split-zero': ('from boltons.iterutils import split_iter',
        'for values in ([2, 0, 3], iter([2, 0, 3])):\n    self.assertEqual(list(split_iter(values, 0, maxsplit=0)), [[2, 0, 3]])',
        'self.assertEqual(list(split_iter([2, 0, 3], 0)), [[2], [3]])'),
    'boltons-chunked-bytes': ('from boltons.iterutils import chunked_iter',
        "self.assertEqual(list(chunked_iter(b'abcde', 2)), [b'ab', b'cd', b'e'])",
        "self.assertEqual(list(chunked_iter('abcde', 2)), ['ab', 'cd', 'e'])\nself.assertEqual(list(chunked_iter([1, 2, 3], 2)), [[1, 2], [3]])"),
    'more-ichunked-zero': ('from more_itertools import ichunked',
        'source = iter([2, 3])\nself.assertEqual(list(ichunked(source, 0)), [])\nself.assertEqual(next(source), 2)\nwith self.assertRaisesRegex(ValueError, "n must be at least 0"):\n    list(ichunked([2], -1))',
        'self.assertEqual([list(c) for c in ichunked([2, 3, 4], 2)], [[2, 3], [4]])'),
    'more-bucket-missing-key': ('from more_itertools import bucket',
        'b = bucket([2, 4, 6], key=lambda x: x % 2)\nself.assertEqual(list(b[7]), [])\nself.assertFalse(9 in b)\nself.assertEqual(list(b), [0])\nself.assertEqual(list(b[0]), [2, 4, 6])',
        'b = bucket([2, 3, 4], key=lambda x: x % 2)\nself.assertTrue(1 in b)\nself.assertEqual(list(b[1]), [3])\nself.assertEqual(list(b[0]), [2, 4])'),
    'more-range-membership': ('from more_itertools import numeric_range',
        'r = numeric_range(0.0, 1.0, 0.1)\nvalues = list(r)\nself.assertEqual(len(r), len(values))\nfor i, value in enumerate(values):\n    self.assertIn(value, r)\n    self.assertEqual(r.index(value), i)',
        'r = numeric_range(1, 8, 2)\nself.assertEqual(list(r), [1, 3, 5, 7])\nself.assertNotIn(2, r)\nwith self.assertRaises(ValueError):\n    r.index(2)'),
    'more-chunked-negative': ('from more_itertools import chunked',
        'for values in ([], [2, 3]):\n    with self.assertRaisesRegex(ValueError, "n must be at least 0"):\n        list(chunked(values, -1))',
        'self.assertEqual(list(chunked([2, 3, 4], 2)), [[2, 3], [4]])\nself.assertEqual(list(chunked([2, 3], None)), [[2, 3]])'),
    'more-range-equality': ('from more_itertools import numeric_range',
        'a, b = numeric_range(3, 4, 1), numeric_range(3, 4, 2)\nself.assertEqual(list(a), list(b))\nself.assertEqual(a, b)\nself.assertEqual(hash(a), hash(b))',
        'self.assertEqual(numeric_range(0), numeric_range(1, 1, 2))\nself.assertNotEqual(numeric_range(3), numeric_range(4))'),
    'more-sliced-negative': ('from more_itertools import sliced',
        'for strict in (False, True):\n    with self.assertRaises(ValueError):\n        list(sliced([2, 3, 4], -1, strict=strict))',
        'self.assertEqual(list(sliced([2, 3, 4], 2)), [[2, 3], [4]])'),
    'more-windowed-zero': ('from more_itertools import windowed',
        'for values in ([], [2, 3]):\n    for n in (0, -1):\n        with self.assertRaises(ValueError):\n            list(windowed(values, n))',
        'self.assertEqual(list(windowed([2, 3, 4], 2)), [(2, 3), (3, 4)])\nself.assertEqual(list(windowed([2], 2, fillvalue=0)), [(2, 0)])\nwith self.assertRaises(ValueError):\n    list(windowed([2], 1, step=0))'),
    'more-predicate-sentinel': ('from more_itertools import locate, replace',
        'seen = []\ndef predicate(*items):\n    seen.append(items)\n    return sum(items) == 7\nself.assertEqual(list(locate([2, 3, 4], predicate, window_size=2)), [1])\nself.assertEqual(list(locate([4], predicate, window_size=2)), [])\nself.assertEqual(seen[-1], (4,))\nself.assertEqual(list(replace([2, 3, 4], lambda *items: sum(items) == 100, [9], window_size=2)), [2, 3, 4])\nself.assertEqual(list(replace([2, 3, 4], predicate, [9], window_size=2)), [2, 9])',
        'self.assertEqual(list(locate([0, 2, 0, 3], bool)), [1, 3])\nself.assertEqual(list(replace([2, 3], lambda x: x == 2, [9])), [9, 3])'),
    'more-combination-size': ('from more_itertools import nth_combination_with_replacement as nth',
        'self.assertEqual(nth([2, 3], 3, 0), (2, 2, 2))\nself.assertEqual(nth([], 0, 0), ())\nfor index in (-2, 1):\n    with self.assertRaises(IndexError):\n        nth([], 0, index)',
        'self.assertEqual(nth([2, 3, 4], 2, 1), (2, 3))\nself.assertEqual(nth([2, 3], 2, -1), (3, 3))'),
    'more-permutation-exception': ('from more_itertools import nth_permutation',
        'with self.assertRaises(IndexError):\n    nth_permutation([2, 3], 3, 0)',
        'with self.assertRaises(ValueError):\n    nth_permutation([2, 3], -1, 0)\nself.assertEqual(nth_permutation([2, 3, 4], 2, 1), (2, 4))'),
}


def code(task_id):
    helpers, reproduce, preserve = CASES[task_id]
    return ('"""Frozen public-description checks, handwritten for development."""\n'
            + 'import unittest\n' + helpers + '\n\n'
            + 'class Reproduce(unittest.TestCase):\n    def test_public_defect(self):\n'
            + textwrap.indent(reproduce, '        ') + '\n\n'
            + 'class Preserve(unittest.TestCase):\n    def test_public_normal_behavior(self):\n'
            + textwrap.indent(preserve, '        ') + '\n')
