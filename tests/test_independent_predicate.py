import ast
import json
from pathlib import Path

import pytest

from docs.experiments import independent_predicate_feedback_v1 as independent
from evals.runner import digest, snapshot
from evals.runtime import Events

PUBLIC = '''import unittest
from example import locate, replace
class Reproduce(unittest.TestCase):
    def test_public_defect(self):
        seen = []
        def predicate(*items):
            seen.append(items)
            return sum(items) == 7
        self.assertEqual(list(locate([2, 3, 4], predicate, window_size=2)), [1])
        self.assertEqual(list(locate([4], predicate, window_size=2)), [])
        self.assertEqual(seen[-1], (4,))
        self.assertEqual(list(replace([2, 3, 4], lambda *items: sum(items) == 100, [9], window_size=2)), [2, 3, 4])
        self.assertEqual(list(replace([2, 3, 4], predicate, [9], window_size=2)), [2, 9])
class Preserve(unittest.TestCase):
    def test_public_normal_behavior(self):
        self.assertEqual(list(locate([0, 2, 0, 3], bool)), [1, 3])
        self.assertEqual(list(replace([2, 3], lambda x: x == 2, [9])), [9, 3])
'''
SOURCE = '''def locate(iterable, pred, window_size=None):
    if window_size is None:
        return [i for i, x in enumerate(iterable) if pred(x)]
    windows = [tuple(iterable[i:i + window_size]) for i in range(max(1, len(iterable) - window_size + 1))]
    return [i for i, w in enumerate(windows) if pred(*(w + (object(),) * (window_size - len(w))))]
def replace(iterable, pred, substitutes, window_size=1):
    i = 0
    while i < len(iterable):
        w = tuple(iterable[i:i + window_size])
        w += (object(),) * (window_size - len(w))
        if pred(*w):
            yield from substitutes
            i += window_size
        else:
            yield iterable[i]
            i += 1
'''


@pytest.fixture
def case(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'example.py').write_text(SOURCE, encoding='utf-8')
    harness = tmp_path / 'public'
    harness.mkdir()
    (harness / 'test_admission.py').write_text(PUBLIC, encoding='utf-8')
    job = {'harness': str(harness), 'harness_hash': digest(snapshot(harness)),
           'allowed_files': ['example.py'], 'package': 'example', 'source_root': '.'}
    return workspace, job


def assertions(text):
    return [ast.dump(n) for n in ast.walk(ast.parse(text)) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == 'assertEqual']


def test_split_keeps_every_original_assertion_and_dependent_setup():
    code, provenance = independent.split_public(PUBLIC)
    assert sorted(assertions(code)) == sorted(assertions(PUBLIC))
    assert len(provenance) == 6
    cls = next(n for n in ast.parse(code).body if isinstance(n, ast.ClassDef) and n.name == 'Reproduce')
    assert len(cls.body) == 4
    short = cls.body[1]
    assert len(short.body) == 4  # seen, predicate, call assertion, dependent last-call assertion
    assert [ast.dump(n) for n in cls.body[0].body[:2]] == [ast.dump(n) for n in short.body[:2]]


@pytest.mark.parametrize('source', [PUBLIC.replace('class Preserve', 'class Other'),
                                     PUBLIC.replace('        self.assertEqual(seen[-1], (4,))\n', ''),
                                     PUBLIC.replace('seen[-1]', 'other[-1]')])
def test_unexpected_public_structure_is_not_silently_rewritten(source):
    with pytest.raises(ValueError):
        independent.split_public(source)


def test_both_failures_are_observed_without_changing_official_tests(case, tmp_path):
    workspace, job = case
    before = digest(snapshot(workspace))
    data = independent.observe(workspace, job, tmp_path / 'probe')
    assert data is not None
    assert len(data['records']) == 6
    failed = [r for r in data['records'] if not r['passed']]
    assert len(failed) == 2
    assert {r['operations'][0]['function'] for r in failed} == {'locate', 'replace'}
    assert all(any(c.get('exception_type') == 'TypeError' for op in r['operations']
                   for c in op['predicate_calls']) for r in failed)
    assert all('operations' not in r for r in data['records'] if r['passed'])
    assert (Path(job['harness']) / 'test_admission.py').read_text(encoding='utf-8') == PUBLIC
    assert digest(snapshot(workspace)) == before


def test_per_case_trace_mismatch_is_rejected(case, tmp_path, monkeypatch):
    workspace, job = case
    original = independent.single.observe
    def altered(*args):
        original(*args)
        path = args[2] / 'observation.json'
        data = json.loads(path.read_text())
        data['payload']['records'][0]['passed'] = False
        path.write_text(json.dumps(data), encoding='utf-8')
    monkeypatch.setattr(independent.single, 'observe', altered)
    assert independent.observe(workspace, job, tmp_path / 'probe') is None


def test_independent_hook_restores_prior_feedback_on_failure(tmp_path, monkeypatch):
    original = independent.guarded.feedback
    def fail(*args):
        assert independent.guarded.feedback is not original
        raise RuntimeError('failed')
    monkeypatch.setattr(independent.guarded, 'run_candidate', fail)
    with pytest.raises(RuntimeError, match='failed'):
        independent.run_candidate(None, {}, Events(tmp_path / 'trace.jsonl', 'test'))
    assert independent.guarded.feedback is original
