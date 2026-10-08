import hashlib

from docs.experiments import class_scoped_comparison_v1 as comparison
from docs.experiments import class_scoped_retrieval_v1 as policy
from docs.experiments import function_index_audit_v1 as functions


def index(tmp_path, files):
    for name, content in files.items():
        (tmp_path / name).write_bytes(content.encode('utf-8'))
    result = functions.FunctionIndex(tmp_path, list(files))
    result.refresh()
    return result


def test_state_owner_initializer_and_methods_replace_unrelated_keyword_matches(tmp_path):
    content = ('class Bucket:\n    def __init__(self):\n        self.cache = {}\n'
               '    def lookup(self, key):\n        return self.cache.get(key)\n'
               '    def keys(self):\n        return list(self.cache)\n'
               'def unrelated():\n    """Bucket lookup missing keys."""\n    return None\n')
    result = policy.retrieve(index(tmp_path, {'code.py': content}), 'Missing Bucket lookups must not invent keys')
    names = [r['symbol'] for r in result['evidence']]
    assert names[0] == 'Bucket.__init__'
    assert set(names[:3]) == {'Bucket.__init__', 'Bucket.lookup', 'Bucket.keys'}
    for row in result['evidence']:
        assert row['content'] in content
        assert row['content_hash'] == hashlib.sha256(content.encode()).hexdigest()
    assert result['metadata']['evidence_chars'] <= 6000 and len(result['evidence']) <= 5


def test_duplicate_class_names_are_not_arbitrarily_promoted(tmp_path):
    result = policy.retrieve(index(tmp_path, {'a.py': 'class Bucket:\n    def __init__(self): pass\n',
                                              'b.py': 'class Bucket:\n    def __init__(self): pass\n'}),
                             'Bucket should preserve state')
    assert result['metadata']['class_scopes'] == []
    assert all(r['reason'] != 'mentioned_class_initializer' for r in result['evidence'])


def test_dotted_class_resolves_one_owner(tmp_path):
    result = policy.retrieve(index(tmp_path, {'a.py': 'class Bucket:\n    def __init__(self): pass\n',
                                              'b.py': 'class Bucket:\n    def __init__(self): pass\n'}),
                             'a.Bucket must preserve state')
    assert result['metadata']['class_scopes'] == [{'path': 'a.py', 'symbol': 'Bucket'}]
    assert result['evidence'][0]['path'] == 'a.py'


def test_explicit_method_before_initializer_without_source_execution(tmp_path):
    result = policy.retrieve(index(tmp_path, {'code.py': 'raise RuntimeError("never import")\nclass Bucket:\n'
                                              '    def __init__(self): pass\n    def lookup(self): return 1\n'}),
                             'Bucket.lookup must preserve results')
    assert result['evidence'][0]['symbol'] == 'Bucket.lookup'


def test_oversized_initializer_skipped_not_truncated(tmp_path):
    content = 'class Bucket:\n    def __init__(self):\n' + '        self.x = 1\n' * 500
    content += '    def lookup(self): return 1\n'
    result = policy.retrieve(index(tmp_path, {'code.py': content}), 'Bucket should preserve lookup')
    assert all(r['symbol'] != 'Bucket.__init__' for r in result['evidence'])
    assert any(r['symbol'] == 'Bucket.__init__' and r['reason'] == 'budget' for r in result['metadata']['discarded'])
    assert result['metadata']['evidence_chars'] <= 6000


def test_all_policy_functions_obey_shared_count_budget_and_repeat_determinism(tmp_path):
    content = 'class Bucket:\n' + ''.join(f'    def method{i}(self): return {i}\n' for i in range(12))
    idx = index(tmp_path, {'code.py': content})
    first = policy.retrieve(idx, 'Bucket must retain methods')
    assert first == policy.retrieve(idx, 'Bucket must retain methods')
    assert len(first['evidence']) == 5


def pairs(candidate_gain=2, candidate_controls=30):
    rows = []
    for i in range(30):
        for name in comparison.POLICIES:
            accepted = i < (12 if name == 'baseline' else 12 + candidate_gain)
            control = i < (30 if name == 'baseline' else candidate_controls)
            rows.append({'task_id': str(i), 'policy': name, 'split': 'development', 'repo': 'sample',
                         'accepted': accepted, 'status': 'passed' if accepted else 'failed_verification',
                         'worker': {'metrics': None}, 'process': {'seconds': 0},
                         'verification': {'groups': {'Target': {'passed': accepted}, 'Controls': {'passed': control}}}})
    return rows


def test_gate_requires_complete_pairs_gain_and_no_control_regression():
    assert comparison.gate(pairs())['eligible']
    assert not comparison.gate(pairs(candidate_gain=1))['eligible']
    assert not comparison.gate(pairs(candidate_gain=5, candidate_controls=29))['eligible']
    assert not comparison.gate(pairs()[:-1])['eligible']
    duplicate = pairs()
    duplicate[-1]['task_id'] = duplicate[-3]['task_id']
    assert not comparison.gate(duplicate)['eligible']


def test_worker_job_cannot_receive_reference_or_private_checks(tmp_path):
    case = {'description': 'problem', 'allowed_files': ['code.py'],
            'before': 'original', 'after': 'secret_reference', 'checks': 'private_tests'}
    job = comparison.make_job(case, tmp_path, [])
    assert set(job) == {'workspace', 'description', 'allowed_files', 'evidence'}
    assert 'secret_reference' not in str(job) and 'private_tests' not in str(job)
