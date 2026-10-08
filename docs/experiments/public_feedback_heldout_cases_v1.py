"""Handwritten description/API examples for the fixed 20 heldout tasks.

Heldout means unused for feedback-policy tuning, not author/model blindness:
earlier retrieval experiments have evaluated these tasks already.
"""
import textwrap

CASES = {
    'boltons-remap-set': ('from boltons.iterutils import remap',
        'self.assertEqual(remap({2, 5}), {2, 5})\nvalue = remap(frozenset([2, 5]))\nself.assertIsInstance(value, frozenset)\nself.assertEqual(value, frozenset([2, 5]))',
        "self.assertEqual(remap({'items': [2, 5]}), {'items': [2, 5]})"),
    'more-falsy-exception': ('''from more_itertools import one, only
class FalsyError(Exception):
    def __bool__(self):
        return False
class NoRepr:
    def __repr__(self):
        raise RuntimeError('repr must not run')''',
        "for function in (one, only):\n    custom = FalsyError('public')\n    with self.assertRaises(FalsyError) as caught:\n        function([NoRepr(), NoRepr()], too_long=custom)\n    self.assertIs(caught.exception, custom)",
        'self.assertEqual(one([7]), 7)\nself.assertEqual(only([7]), 7)\nself.assertEqual(only([], default=8), 8)\nwith self.assertRaises(ValueError):\n    one([])'),
    'more-batch-count': ('from more_itertools import constrained_batches',
        'for count in (0, -2):\n    with self.assertRaises(ValueError):\n        list(constrained_batches([b"ab"], max_size=3, max_count=count))',
        'self.assertEqual(list(constrained_batches([b"ab", b"c", b"de"], max_size=3, max_count=2)), [(b"ab", b"c"), (b"de",)])\nself.assertEqual(list(constrained_batches([b"ab", b"c"], max_size=3)), [(b"ab", b"c")])'),
    'more-seekable-zero': ('from more_itertools import seekable',
        's = seekable([2, 3], maxlen=0)\nself.assertTrue(bool(s))\nself.assertEqual(s.peek(), 2)\nself.assertEqual(s.peek(), 2)\nself.assertEqual(next(s), 2)\nself.assertEqual(next(s), 3)\nself.assertFalse(bool(s))',
        's = seekable([2, 3])\nself.assertEqual(s.peek(), 2)\nself.assertEqual(next(s), 2)\ns.seek(0)\nself.assertEqual(next(s), 2)\nself.assertEqual(list(s), [3])\nwith self.assertRaises(StopIteration):\n    s.peek()'),
    'more-combination-index': ('from more_itertools import combination_with_replacement_index as index\nfrom itertools import combinations_with_replacement',
        'pool = [2, None, 3]\nfor size in (0, 1, 2, 3):\n    for expected, value in enumerate(combinations_with_replacement(pool, size)):\n        self.assertEqual(index(value, pool), expected)',
        'self.assertEqual(index((2, 3), [2, 3, 4]), 1)\nfor value in ((3, 2), (8,)):\n    with self.assertRaises(ValueError):\n        index(value, [2, 3, 4])'),
    'more-split-empty': ('from more_itertools import split_before, split_after, split_when',
        'for function in (split_before, split_after):\n    self.assertEqual(list(function([], lambda x: x == 0, maxsplit=0)), [])\nself.assertEqual(list(split_when([], lambda a, b: a != b, maxsplit=0)), [])',
        'for function in (split_before, split_after):\n    self.assertEqual(list(function([2, 0, 3], lambda x: x == 0, maxsplit=0)), [[2, 0, 3]])\nself.assertEqual(list(split_before([2, 0, 3], lambda x: x == 0)), [[2], [0, 3]])\nself.assertEqual(list(split_after([2, 0, 3], lambda x: x == 0)), [[2, 0], [3]])\nself.assertEqual(list(split_when([2, 2, 3], lambda a, b: a != b)), [[2, 2], [3]])'),
    'more-value-chain-error': ('''from more_itertools import value_chain
class Broken:
    def __iter__(self):
        yield 2
        raise TypeError('public iteration failure')''',
        "with self.assertRaisesRegex(TypeError, 'public iteration failure'):\n    list(value_chain(Broken()))",
        'self.assertEqual(list(value_chain(2, [3, 4], None)), [2, 3, 4, None])'),
    'more-interleave-empty': ('from more_itertools import interleave_evenly',
        'self.assertEqual(list(interleave_evenly([])), [])\nself.assertEqual(list(interleave_evenly([], lengths=[])), [])',
        "self.assertEqual(list(interleave_evenly([[2, 3], ['a', 'b']])), [2, 'a', 3, 'b'])"),
    'more-reverse-empty-range': ('from more_itertools import numeric_range',
        'for r in (numeric_range(0), numeric_range(3, 3), numeric_range(1, 5, -1)):\n    self.assertEqual(list(reversed(r)), [])',
        'r = numeric_range(2, 8, 2)\nself.assertEqual(list(r), [2, 4, 6])\nself.assertEqual(list(reversed(r)), [6, 4, 2])'),
    'more-negative-range-slice': ('from more_itertools import numeric_range',
        'r = numeric_range(2, 14, 2)\nfor selection in (slice(None, None, -1), slice(None, 1, -2), slice(-2, None, -1), slice(4, 0, -2)):\n    self.assertEqual(list(r[selection]), list(r)[selection])',
        'r = numeric_range(2, 14, 2)\nself.assertEqual(list(r[1:4:2]), [4, 8])\nself.assertEqual(r[-1], 12)'),
    'more-product-repeat': ('from more_itertools import nth_product, product_index\nfrom itertools import product',
        'expected = list(product([2, 3], repeat=2))\nfor i, value in enumerate(expected):\n    self.assertEqual(nth_product(i, iter([2, 3]), repeat=2), value)\n    self.assertEqual(product_index(value, iter([2, 3]), repeat=2), i)',
        'self.assertEqual(nth_product(2, [2, 3], [8, 9]), (3, 8))\nself.assertEqual(product_index((3, 8), [2, 3], [8, 9]), 2)'),
    'more-gray-partial-repeat': ('from more_itertools import gray_product, partial_product',
        'for function in (gray_product, partial_product):\n    expected = list(function([2, 3], [8, 9], repeat=2))\n    self.assertEqual(list(function(iter([2, 3]), iter([8, 9]), repeat=2)), expected)',
        'self.assertEqual(list(partial_product([2, 3], [8, 9])), [(2, 8), (3, 8), (3, 9)])\nself.assertEqual(set(gray_product([2, 3], [8, 9])), {(2, 8), (3, 8), (2, 9), (3, 9)})'),
    'more-reversed-values': ('from more_itertools import numeric_range\nfrom datetime import datetime, timedelta',
        'r = numeric_range(0.0, 0.8, 0.1)\nself.assertEqual(list(reversed(r)), list(r)[::-1])\nr = numeric_range(datetime.max - timedelta(days=2), datetime.max, timedelta(days=1))\nself.assertEqual(list(reversed(r)), list(r)[::-1])',
        'self.assertEqual(list(reversed(numeric_range(2, 6))), [5, 4, 3, 2])\nself.assertEqual(list(reversed(numeric_range(0))), [])'),
    'more-broadcast-single-use': ('''from more_itertools import zip_broadcast
class SingleUse:
    def __init__(self):
        self.opens = 0
    def __iter__(self):
        self.opens += 1
        if self.opens > 1:
            raise RuntimeError('opened twice')
        return iter([2, 3])''',
        's = SingleUse()\nself.assertEqual(list(zip_broadcast(s, 7)), [(2, 7), (3, 7)])\nself.assertEqual(s.opens, 1)',
        'self.assertEqual(list(zip_broadcast([2, 3], [8, 9])), [(2, 8), (3, 9)])\nself.assertEqual(list(zip_broadcast(7, [2, 3])), [(7, 2), (7, 3)])'),
    'more-last-typeerror': ('''from more_itertools import last
class BrokenReverse:
    def __reversed__(self):
        raise TypeError('public reverse failure')
    def __iter__(self):
        return iter([2, 3])''',
        "for kwargs in ({}, {'default': 8}):\n    with self.assertRaisesRegex(TypeError, 'public reverse failure'):\n        last(BrokenReverse(), **kwargs)",
        'self.assertEqual(last([2, 3]), 3)\nself.assertEqual(last(iter([2, 3])), 3)\nself.assertEqual(last([], default=8), 8)'),
    'boltons-xfrange-descending': ('from boltons.iterutils import frange, xfrange',
        'self.assertEqual(list(xfrange(5, start=1, step=-1)), [5, 4, 3, 2])\nself.assertEqual(list(xfrange(0, start=1, step=0.1)), frange(0, start=1, step=0.1))',
        'self.assertEqual(list(xfrange(1, start=7, step=2)), [1, 3, 5])'),
    'boltons-backoff-zero': ('from boltons.iterutils import backoff',
        'self.assertEqual(backoff(0, 4), [0, 1, 2, 4])\nself.assertEqual(backoff(0, 4, count=6), [0, 1, 2, 4, 4, 4])',
        'self.assertEqual(backoff(1, 4), [1, 2, 4])\nself.assertEqual(backoff(1, 4, count=2), [1, 2])'),
    'boltons-repeat-equality': ('from boltons.iterutils import backoff_iter\nfrom itertools import islice',
        "count = ''.join(['re', 'peat'])\nself.assertEqual(list(islice(backoff_iter(1, 4, count=count), 6)), [1, 2, 4, 4, 4, 4])",
        'self.assertEqual(list(backoff_iter(1, 4, count=4)), [1, 2, 4, 4])'),
    'toolz-partition-length': ('''from toolz import partition_all
class BadLength(list):
    def __len__(self):
        return 2''',
        'with self.assertRaises(LookupError):\n    list(partition_all(2, BadLength([2, 3, 4])))',
        'self.assertEqual(list(partition_all(2, [2, 3, 4])), [(2, 3), (4,)])\nself.assertEqual(list(partition_all(2, iter([2, 3, 4]))), [(2, 3), (4,)])'),
    'toolz-merge-mapping': ('''from toolz import merge_with
from collections.abc import Mapping
class PublicMapping(Mapping):
    def __iter__(self):
        return iter(['a', 'b'])
    def __len__(self):
        return 2
    def __getitem__(self, key):
        return {'a': 2, 'b': 3}[key]''',
        "self.assertEqual(merge_with(sum, PublicMapping()), {'a': 2, 'b': 3})",
        "self.assertEqual(merge_with(sum, {'a': 2}, {'a': 3, 'b': 4}), {'a': 5, 'b': 4})"),
}


def code(task_id):
    helpers, reproduce, preserve = CASES[task_id]
    return ('"""Frozen heldout public-description checks; handwritten."""\nimport unittest\n'
            + helpers + '\n\nclass Reproduce(unittest.TestCase):\n    def test_public_defect(self):\n'
            + textwrap.indent(reproduce, '        ')
            + '\n\nclass Preserve(unittest.TestCase):\n    def test_public_normal_behavior(self):\n'
            + textwrap.indent(preserve, '        ') + '\n')
