import json
import shutil
import sys
from pathlib import Path

import pytest

from evals.real_tasks import VISIBLE, configure_visible_tools, run_real, verify, visible_checks
from evals.runner import digest, snapshot
from evals.runtime import Events, make_tools
from evals.schema import RunConfig


@pytest.fixture
def real_case(tmp_path):
    source = tmp_path / 'admitted'
    for label, fixed in (('before', False), ('after', True)):
        package = source / label / 'src/click'
        package.mkdir(parents=True)
        (package / '__init__.py').write_text('from .core import FIXED\n', encoding='utf-8')
        (package / 'core.py').write_text(f'FIXED = {fixed}\n', encoding='utf-8')
        (package / 'other.py').write_text('OTHER = True\n', encoding='utf-8')
        (source / label / 'LICENSE.txt').write_text('retained upstream license', encoding='utf-8')
    checks = tmp_path / 'parent-checks'
    checks.mkdir()
    (checks / 'test_admission.py').write_text(
        'import unittest, click\n'
        'class Target(unittest.TestCase):\n'
        '    def test_hidden_requirement(self): self.assertTrue(click.FIXED)\n'
        'class Controls(unittest.TestCase):\n'
        '    def test_normal(self): self.assertIn(click.FIXED, (True, False))\n', encoding='utf-8')
    case = {'case_id': 'fake-real-task', 'public_problem': 'Correct the reported behavior.',
            'changed_source_files': ['src/click/core.py']}
    row = {'checks_hash': digest(snapshot(checks)),
           'revisions': {label: {'tree_hash': digest(snapshot(source / label))} for label in ('before', 'after')}}
    return case, row, checks, source, {'executable': sys.executable}


def test_public_checks_exclude_target(real_case):
    text = visible_checks(real_case[2])
    assert 'Controls' in text and 'Target' not in text and 'test_hidden_requirement' not in text


@pytest.mark.parametrize('mode,accepted', [('unchanged', False), ('reference', True), ('scripted', True)])
def test_real_protocol_original_and_oracle_controls(tmp_path, real_case, mode, accepted):
    report = run_real(*real_case, RunConfig(mode=mode), tmp_path / 'runs')
    assert report['accepted'] is accepted, report
    assert report['benchmark_eligible'] is False
    assert 'src/click/other.py' in report['allowed_files']
    assert report['verification']['regression']['passed']
    assert report['verification']['target']['passed'] is accepted
    workspace = Path(report['artifacts']) / 'workspace'
    assert (workspace / 'LICENSE.txt').read_text() == 'retained upstream license'
    assert 'Target' not in (workspace / '.real-visible/test_admission.py').read_text()
    if mode == 'scripted':
        trace = (workspace.parent / 'trace.jsonl').read_text(encoding='utf-8')
        assert VISIBLE in trace


def test_live_job_has_no_oracle_or_target(tmp_path, real_case, monkeypatch):
    captured = {}

    def worker(command, cwd, timeout, stdout, stderr, env):
        job_path = Path(command[-1])
        captured.update(json.loads(job_path.read_text(encoding='utf-8')))
        (job_path.parent / 'worker-result.json').write_text(json.dumps({'status': 'completed', 'metrics': None}))
        return {'timed_out': False, 'returncode': 0, 'seconds': 0}

    monkeypatch.setattr('evals.real_tasks.run_process', worker)
    report = run_real(*real_case, RunConfig(mode='live'), tmp_path / 'runs')
    assert report['status'] == 'failed_verification'
    assert captured['description'] == real_case[0]['public_problem']
    assert 'oracle_edits' not in captured and 'changed_source_files' not in captured
    assert 'test_hidden_requirement' not in json.dumps(captured)
    assert 'before_commit' not in captured and 'after_commit' not in captured


def test_grading_rejects_visible_test_tampering(tmp_path, real_case):
    case, _row, checks, source, environment = real_case
    workspace = tmp_path / 'workspace'
    shutil.copytree(source / 'before', workspace)
    (workspace / 'tests').mkdir()
    test = workspace / 'tests/test_fake.py'
    test.write_text('original')
    original = snapshot(workspace)
    (workspace / 'src/click/core.py').write_text('FIXED = True\n')
    test.write_text('tampered')
    root = tmp_path / 'run'
    root.mkdir()
    result = verify(case, source, checks, workspace, original, ['src/click/core.py'], root, environment['executable'])
    assert not result['passed'] and result['scope_violations'] == ['tests/test_fake.py']
    assert not (root / 'grading').exists()


def test_real_visible_tool_blocks_other_shell_commands(tmp_path, real_case):
    source = real_case[3] / 'before'
    public = source / '.real-visible'
    public.mkdir()
    (public / 'test_admission.py').write_text(visible_checks(real_case[2]), encoding='utf-8')
    tools = make_tools(source, ['src/click/core.py'], Events(tmp_path / 'trace.jsonl', 'test'), 5)
    configure_visible_tools(tools, source, sys.executable)
    bash = next(tool for tool in tools if tool.name == 'bash')
    assert 'Error:' in bash.execute(command='python -m unittest discover -s tests -v')
    assert 'exit code: 0' in bash.execute(command=VISIBLE)
