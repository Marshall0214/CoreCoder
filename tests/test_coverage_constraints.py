import json
from types import SimpleNamespace

import pytest

from corecoder.llm import LLMResponse
from docs.experiments.coverage_context_v2 import retrieve
from docs.experiments.constrained_patch_v1 import request


def test_qualified_target_reserved_and_unrelated_methods_cannot_displace_it(tmp_path):
    (tmp_path / 'app.py').write_text('class Formatter:\n    def write_usage(self):\n        return "bad"\n    def write_text(self):\n        return "irrelevant"\n')
    result = retrieve(tmp_path, ['app.py'], 'Formatter.write_usage must render empty input.')
    assert ['app.py', 'Formatter.write_usage'] in [list(x) for x in result['metadata']['required']]
    assert result['evidence'][0]['symbol'] == 'Formatter.write_usage'
    assert result['metadata']['missing_required'] == []


def test_coupled_hash_and_context_exit_are_covered(tmp_path):
    (tmp_path / 'app.py').write_text('class Span:\n    def __eq__(self, other):\n        return True\n    def __hash__(self):\n        return 1\nclass Context:\n    def with_resource(self, manager):\n        return manager\n    def __exit__(self, *exc):\n        return False\n')
    equal = retrieve(tmp_path, ['app.py'], 'Span objects must compare equal and have equal hashes.')
    assert {'Span.__eq__', 'Span.__hash__'} <= {r['symbol'] for r in equal['evidence']}
    resource = retrieve(tmp_path, ['app.py'], 'Context-managed resources registered with with_resource must receive exception details on exit.')
    assert {'Context.with_resource', 'Context.__exit__'} <= {r['symbol'] for r in resource['evidence']}


def test_prose_output_does_not_force_unrelated_output_method(tmp_path):
    (tmp_path / 'app.py').write_text('class Result:\n    def output(self):\n        return "text"\ndef option():\n    return None\n')
    result = retrieve(tmp_path, ['app.py'], 'Help output must reflect the effective default.')
    assert result['metadata']['required'] == []


def test_over_budget_required_target_blocks_instead_of_silently_disappearing(tmp_path):
    (tmp_path / 'app.py').write_text('def repair_target():\n    return "' + 'x' * 6500 + '"\n')
    with pytest.raises(ValueError, match='coverage exceeds'):
        retrieve(tmp_path, ['app.py'], 'repair_target must work')


@pytest.mark.parametrize('kind', ['empty', 'identical', 'unseen', 'syntax', 'cancelling', 'valid'])
def test_constrained_patch_is_atomic_and_requires_real_change(tmp_path, kind):
    workspace = tmp_path / 'source'
    workspace.mkdir()
    original = 'def repair_target():\n    return 1\n'
    (workspace / 'app.py').write_text(original)
    evidence = retrieve(workspace, ['app.py'], 'repair_target must return 2')['evidence']
    edit = dict(file='app.py', old='return 1', new='return 2')
    edits = [edit]
    if kind == 'empty':
        edits = []
    elif kind == 'identical':
        edit['new'] = edit['old']
    elif kind == 'unseen':
        edit['old'] = 'missing code'
    elif kind == 'syntax':
        edit['new'] = 'return ('
    elif kind == 'cancelling':
        # Both anchors are supplied, but the pair restores the original source.
        edits = [dict(file='app.py', old='return 1', new='1'),
                 dict(file='app.py', old='1', new='return 1')]
    llm = SimpleNamespace(chat=lambda *args, **kwargs: LLMResponse(content=json.dumps({'edits': edits})))
    result = request(llm, workspace, {'description': 'repair_target must return 2', 'allowed_files': ['app.py']}, evidence, tmp_path, 'initial')
    assert (result['status'] == 'completed') is (kind == 'valid')
    expected = original.replace('return 1', 'return 2') if kind == 'valid' else original
    assert (workspace / 'app.py').read_text() == expected
