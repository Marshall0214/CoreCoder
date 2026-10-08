import pytest

from docs.experiments import failure_context_v1 as selection

SOURCE = '''def seed():
    return 1

class Range:
    def __init__(self):
        self.value = 1
    def __contains__(self, item):
        return item == self.value

def fault():
    raise ValueError('public')
'''


def fixture_source(tmp_path):
    (tmp_path / 'code.py').write_text(SOURCE)
    index = selection.policy.baseline.functions.FunctionIndex(tmp_path, ['code.py'])
    index.refresh()
    chunk = next(c for c in index.chunks if index.names[(c.path, c.start_line, c.end_line)] == 'seed')
    seeds = selection.policy.baseline.functions.pack(index, [(1, chunk)])['evidence']
    return seeds


def test_failure_frame_promotes_whole_current_function(tmp_path):
    seeds = fixture_source(tmp_path)
    stderr = f'  File "{tmp_path / "code.py"}", line 11, in fault\n'
    result = selection.context(tmp_path, ['code.py'], seeds, '', stderr)
    assert result['evidence'][0]['symbol'] == 'fault'
    assert 'def fault()' in result['evidence'][0]['content']
    assert result['metadata']['selection'][0]['reason'] == 'public_failure_frame'


def test_public_membership_promotes_contains_without_setup_constructor(tmp_path):
    seeds = fixture_source(tmp_path)
    code = 'def test(self):\n    r = Range()\n    self.assertIn(1, r)\n'
    result = selection.context(tmp_path, ['code.py'], seeds, code, '')
    assert [r['symbol'] for r in result['evidence']] == ['Range.__contains__', 'seed']
    assert result['metadata']['selection'][0]['reason'] == 'public_membership_contract'


def test_foreign_or_out_of_scope_traceback_never_becomes_evidence(tmp_path):
    seeds = fixture_source(tmp_path)
    stderr = f'File "{tmp_path.parent / "code.py"}", line 11, in fault\nFile "{tmp_path / "other.py"}", line 11, in fault\n'
    result = selection.context(tmp_path, ['code.py'], seeds, '', stderr)
    assert [r['symbol'] for r in result['evidence']] == ['seed']


def test_stale_seed_hash_rejected(tmp_path):
    seeds = fixture_source(tmp_path)
    (tmp_path / 'code.py').write_text(SOURCE + '\n')
    with pytest.raises(ValueError):
        selection.context(tmp_path, ['code.py'], seeds, '', '')


def test_local_type_binding_does_not_leak_between_public_tests(tmp_path):
    seeds = fixture_source(tmp_path)
    code = 'def first(self):\n    r = Range()\ndef second(self):\n    self.assertIn(1, r)\n'
    assert [r['symbol'] for r in selection.context(tmp_path, ['code.py'], seeds, code, '')['evidence']] == ['seed']


def test_reselection_keeps_original_caps_and_byte_hashes(tmp_path):
    seeds = fixture_source(tmp_path)
    result = selection.context(tmp_path, ['code.py'], seeds,
                               'def test(self):\n    r = Range()\n    self.assertIn(1, r)', '')
    assert len(result['evidence']) <= 5 and sum(len(r['content']) for r in result['evidence']) <= 6000
    selection.policy.repair.validate_evidence(tmp_path, ['code.py'], result['evidence'])
    assert (tmp_path / 'code.py').read_text() == SOURCE
