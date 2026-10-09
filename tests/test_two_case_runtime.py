import json
from pathlib import Path

import pytest

from docs.experiments import two_case_diagnosis_v1 as diagnosis
from docs.experiments import two_case_probe_v1 as child
from docs.experiments import two_case_runtime_v1 as runtime
from evals.runner import digest, snapshot

SOURCE = '''class numeric_range:
    def __init__(self,*args): self.args = args
    def __iter__(self): return iter([0.0,0.1])
    def __len__(self): return 2
    def __contains__(self,value): return False
    def index(self,value): return 0
def _build_prompt(text,suffix):
    unrelated = 'do-not-capture'
    return text + suffix
def visible_input(prompt): return prompt + '5'
'''
CHECKS = '''import unittest
from example import numeric_range,_build_prompt,visible_input
class Reproduce(unittest.TestCase):
    def test_range(self):
        r = numeric_range(0.0,1.0,0.1)
        self.assertIn(0.1,r)
    def test_prompt(self):
        self.assertEqual(_build_prompt('Count','')+visible_input(' '),'Count5')
class Preserve(unittest.TestCase):
    def test_normal(self): self.assertEqual(len(numeric_range(1,8,2)),2)
class Target(unittest.TestCase):
    def test_private(self):
        numeric_range(999)
        raise AssertionError('private-must-not-run')
'''


@pytest.fixture
def case(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'example.py').write_text(SOURCE, encoding='utf-8')
    harness = tmp_path / 'public'
    harness.mkdir()
    (harness / 'test_admission.py').write_text(CHECKS, encoding='utf-8')
    job = {'harness': str(harness), 'harness_hash': digest(snapshot(harness)),
           'source_root': '.', 'package': 'example', 'allowed_files': ['example.py']}
    outcomes = {'public': {'Reproduce': {'tests_run': 2, 'failures': 2, 'errors': 0},
                           'Preserve': {'tests_run': 1, 'failures': 0, 'errors': 0}}}
    return workspace, job, outcomes


def test_actual_public_operations_and_prompt_arguments_observed(case, tmp_path):
    workspace, job, outcomes = case
    before = digest(snapshot(workspace))
    data = runtime.observe(workspace, job, tmp_path / 'probe', outcomes)
    assert data is not None
    assert data['numeric'][0]['iteration'][1] == {'value': 0.1, 'contains': False, 'index': 0}
    assert any(c['function'] == 'visible_input' and c['arguments'] == {'prompt': ' '} for c in data['prompt_calls'])
    assert all(r['arguments'] != [999] for r in data['numeric'])
    assert 'do-not-capture' not in json.dumps(data) and 'private-must-not-run' not in json.dumps(data)
    assert digest(snapshot(workspace)) == before


def test_result_mismatch_falls_back(case, tmp_path):
    workspace, job, outcomes = case
    outcomes['public']['Reproduce']['failures'] = 1
    assert runtime.observe(workspace, job, tmp_path / 'probe', outcomes) is None


def test_tampered_harness_rejected(case, tmp_path):
    workspace, job, outcomes = case
    (Path(job['harness']) / 'test_admission.py').write_text('pass', encoding='utf-8')
    with pytest.raises(ValueError, match='harness changed'):
        runtime.observe(workspace, job, tmp_path / 'probe', outcomes)


def test_primitive_does_not_execute_repr_or_iterator():
    class Dangerous:
        def __repr__(self): raise AssertionError('repr')
        def __iter__(self): raise AssertionError('iterator')
    assert child.primitive(Dangerous()) == {'type': 'Dangerous', 'captured': False}
    assert child.primitive(float('nan'))['captured'] is False


def test_overlong_range_observation_rejected(case, tmp_path):
    workspace, job, outcomes = case
    source = SOURCE.replace('iter([0.0,0.1])', 'iter(range(14))')
    (workspace / 'example.py').write_text(source, encoding='utf-8')
    assert runtime.observe(workspace, job, tmp_path / 'probe', outcomes) is None


def test_human_hypothesis_only_changes_owned_prompt_source(tmp_path):
    target = tmp_path / 'src/click/termui.py'
    target.parent.mkdir(parents=True)
    target.write_text('def prompt_func(f,prompt_suffix):\n    return f(" ")\n'
                      'def confirm(visible_prompt_func,prompt_suffix):\n'
                      '    return visible_prompt_func(" ").lower().strip()\n', encoding='utf-8')
    diagnosis.human_patch(tmp_path, 'click-prompt-suffix')
    source = target.read_text(encoding='utf-8')
    assert source.count('" " if prompt_suffix else ""') == 2
    namespace = {}
    exec(compile(source, str(target), 'exec'), namespace)  # noqa: S102 - generated local fixture, never model input
    assert namespace['prompt_func'](lambda s: s, '') == ''
    assert namespace['prompt_func'](lambda s: s, ': ') == ' '


def test_human_nonunique_anchor_is_rejected(tmp_path):
    target = tmp_path / 'src/click/termui.py'
    target.parent.mkdir(parents=True)
    target.write_text('pass\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Nonunique'):
        diagnosis.human_patch(tmp_path, 'click-prompt-suffix')
