import ast
import hashlib

import pytest

from repairflow import issue_context as module

SOURCE = '''from helpers import clean
from math import floor

def target(x):
    return direct(x)

def related(x):
    return clean(x)

def direct(x):
    return x + 1

def noise_one(x):
    return x

def noise_two(x):
    return x

def noise_three(x):
    return x
'''


def baseline(source, required=('target',), names=('target', 'noise_one', 'noise_two', 'noise_three', 'direct')):
    lines = source.splitlines(keepends=True)
    nodes = {n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    rows = []
    for name in names:
        node = nodes[name]
        rows.append({'path': 'pkg.py', 'symbol': name, 'start_line': node.lineno, 'end_line': node.end_lineno,
                     'content': ''.join(lines[node.lineno - 1:node.end_lineno]),
                     'content_hash': hashlib.sha256(source.encode()).hexdigest(), 'reason': 'baseline'})
    return {'evidence': rows, 'metadata': {'policy': 'baseline', 'required': [['pkg.py', n] for n in required],
            'missing_required': [], 'discarded': [], 'chars': sum(len(r['content']) for r in rows)}}


def prepare(tmp_path, monkeypatch, source=SOURCE, **kwargs):
    (tmp_path / 'pkg.py').write_bytes(source.encode())
    monkeypatch.setattr(module, 'baseline_retrieve', lambda *args: baseline(source, **kwargs))


def test_imports_public_helpers_and_direct_helpers_replace_noise(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    result = module.retrieve(tmp_path, ['pkg.py'], 'target must work', 'target(1)\nrelated(1)')
    names = [r['symbol'] for r in result['evidence']]
    assert names[:4] == ['target', '<module-imports>', 'related', 'direct']
    assert len(names) == 5 and 'noise_two' not in names
    assert 'from helpers import clean' in result['evidence'][1]['content']
    assert result['metadata']['policy'] == 'module-bindings-v1'
    assert result['metadata']['chars'] <= 6000 and result['metadata']['max_fragments'] == 5
    assert module.retrieve(tmp_path, ['pkg.py'], 'target must work', 'target(1)\nrelated(1)') == result
    module.validate_evidence(tmp_path, ['pkg.py'], result['evidence'])


def test_all_required_targets_win_over_optional_imports(tmp_path, monkeypatch):
    names = ('target', 'noise_one', 'noise_two', 'noise_three', 'direct')
    prepare(tmp_path, monkeypatch, required=names, names=names)
    result = module.retrieve(tmp_path, ['pkg.py'], '', 'related(1)')
    assert {r['symbol'] for r in result['evidence']} == set(names)
    assert any(r['symbol'] == '<module-imports>' and r['reason'] == 'budget' for r in result['metadata']['discarded'])


def test_source_budget_not_increased_for_imports(tmp_path, monkeypatch):
    source = SOURCE.replace('    return direct(x)', '    marker = "' + 'a' * 5900 + '"\n    return direct(x)')
    prepare(tmp_path, monkeypatch, source, names=('target',))
    result = module.retrieve(tmp_path, ['pkg.py'], '', 'related(1)')
    assert sum(len(r['content']) for r in result['evidence']) <= 6000
    assert result['evidence'][0]['symbol'] == 'target'
    assert any(r['reason'] == 'budget' for r in result['metadata']['discarded'])


def test_nested_imports_are_not_reported_as_module_bindings(tmp_path, monkeypatch):
    source = SOURCE.replace('    return direct(x)', '    import nested_only\n    return direct(x)')
    prepare(tmp_path, monkeypatch, source)
    result = module.retrieve(tmp_path, ['pkg.py'], '', '')
    imports = [r for r in result['evidence'] if r['symbol'] == '<module-imports>']
    assert all('nested_only' not in r['content'] for r in imports)


def test_stale_baseline_evidence_rejected_before_packing(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch)
    (tmp_path / 'pkg.py').write_text(SOURCE + '\n# changed', encoding='utf-8')
    with pytest.raises(ValueError, match='version changed'):
        module.retrieve(tmp_path, ['pkg.py'], '', '')


def test_path_escape_rejected_before_reading(tmp_path):
    with pytest.raises(ValueError):
        module.retrieve(tmp_path, ['../outside.py'], '', '')


def test_modules_are_parsed_never_imported_or_executed(tmp_path, monkeypatch):
    source = "raise AssertionError('must not execute repository code')\n" + SOURCE
    prepare(tmp_path, monkeypatch, source)
    result = module.retrieve(tmp_path, ['pkg.py'], '', '')
    assert result['evidence'][0]['symbol'] == 'target'


def test_import_characters_are_separately_bounded(tmp_path, monkeypatch):
    source = '\n'.join('import package_' + 'x' * 90 + str(i) for i in range(20)) + '\n' + SOURCE
    prepare(tmp_path, monkeypatch, source)
    result = module.retrieve(tmp_path, ['pkg.py'], '', 'related(1)')
    assert result['metadata']['import_chars'] <= 1200
    assert result['metadata']['chars'] <= 6000 and len(result['evidence']) <= 5
