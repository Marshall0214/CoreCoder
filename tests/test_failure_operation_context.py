import json

import pytest

from docs.experiments import failure_operation_compare_v1 as compare
from docs.experiments import failure_operation_context_v1 as selection

CODE = '''class Range:
    def __init__(self):
        self.value = 1
    def index(self, value):
        return 0
    def __contains__(self, value):
        return value == self.value
    def __reversed__(self):
        return iter([self.value])
    def __len__(self):
        return 1
class Option:
    def get_default(self):
        return True
    def get_help_record(self):
        return str(self.get_default())
    def get_other_record(self):
        return str(self.get_default())
def unrelated():
    return 1
'''


def seeds(root, symbols):
    index = selection.previous.baseline.functions.FunctionIndex(root, ['code.py'])
    index.refresh()
    chunks = {index.names[(c.path, c.start_line, c.end_line)]: c for c in index.chunks}
    return selection.previous.baseline.functions.pack(index, [(10 - i, chunks[name]) for i, name in enumerate(symbols)])['evidence']


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / 'code.py').write_text(CODE, encoding='utf-8')
    return tmp_path


def select(root, seed, code, line):
    return selection.select(root, ['code.py'], seed, code,
                            f'File "<public-checks>/test_admission.py", line {line}, in test')


@pytest.mark.parametrize('assertion', ['self.assertIn(1, r)', 'self.assertNotIn(2, r)', 'self.assertTrue(1 in r)'])
def test_failed_membership_resolves_implicit_method(workspace, assertion):
    code = f'def test(self):\n    r = Range()\n    {assertion}\n'
    result = select(workspace, seeds(workspace, ['Range.index']), code, 3)
    assert result['evidence'][0]['symbol'] == 'Range.__contains__'


@pytest.mark.parametrize(('expression', 'method'), [('reversed(r)', '__reversed__'), ('len(r)', '__len__')])
def test_other_builtin_operations_resolve_owner(workspace, expression, method):
    code = f'def test(self):\n    r = Range()\n    self.assertEqual(list({expression}), [])\n'
    result = select(workspace, seeds(workspace, ['Range.index']), code, 3)
    assert result['evidence'][0]['symbol'] == 'Range.' + method


def test_public_import_alias_resolves_constructor(workspace):
    code = 'from code import Range as R\ndef test(self):\n    r = R()\n    self.assertIn(1, r)\n'
    assert select(workspace, seeds(workspace, ['Range.index']), code, 4)['evidence'][0]['symbol'] == 'Range.__contains__'


def test_help_flag_promotes_reverse_caller_without_task_name(workspace):
    code = 'def test(self):\n    output = invoke(["--help"])\n    self.assertIn("default", output)\n'
    result = select(workspace, seeds(workspace, ['Option.get_default']), code, 3)
    assert [r['symbol'] for r in result['evidence']] == ['Option.get_help_record', 'Option.get_default']
    assert result['metadata']['operation_candidates'][0]['reason'] == 'failed_public_flag_reverse_caller'


def test_foreign_import_is_not_mistaken_for_owned_class(workspace):
    code = 'from external import Range\ndef test(self):\n    r = Range()\n    self.assertIn(1, r)\n'
    seed = seeds(workspace, ['Range.index'])
    assert [r['symbol'] for r in select(workspace, seed, code, 4)['evidence']] == ['Range.index']


def test_successful_test_operations_do_not_enter_failure_context(workspace):
    code = ('def test(self):\n    self.assertEqual(0, 1)\n'
            'def other(self):\n    r = Range()\n    self.assertIn(1, r)\n')
    seed = seeds(workspace, ['Option.get_default'])
    result = select(workspace, seed, code, 2)
    assert result['evidence'] == selection.REFRESH(workspace, ['code.py'], seed)['evidence']


def test_rebound_variable_does_not_supply_type(workspace):
    code = 'def test(self):\n    r = Range()\n    r = object()\n    self.assertIn(1, r)\n'
    seed = seeds(workspace, ['Range.index'])
    result = select(workspace, seed, code, 4)
    assert [r['symbol'] for r in result['evidence']] == ['Range.index']


def test_current_edited_seed_retained_before_unrelated_seeds(workspace):
    names = ['Range.__init__', 'Range.__len__', 'Range.__reversed__', 'unrelated', 'Range.index']
    seed = seeds(workspace, names)
    path = workspace / 'code.py'
    path.write_text(CODE.replace('return 0', 'return 2'), encoding='utf-8')
    code = 'def test(self):\n    r = Range()\n    self.assertIn(1, r)\n'
    result = select(workspace, seed, code, 3)
    assert [r['symbol'] for r in result['evidence']][:2] == ['Range.__contains__', 'Range.index']
    assert len(result['evidence']) <= 5
    assert sum(len(r['content']) for r in result['evidence']) <= 6000
    selection.previous.repair.validate_evidence(workspace, ['code.py'], result['evidence'])


def test_no_failure_frame_keeps_seed_evidence_identical(workspace):
    seed = seeds(workspace, ['Range.index'])
    result = selection.select(workspace, ['code.py'], seed, 'def test():\n    pass\n', '')
    assert result['evidence'] == selection.REFRESH(workspace, ['code.py'], seed)['evidence']


def test_shared_payload_does_not_read_grader_or_reference(tmp_path):
    feedback = {'test_code': 'public', 'observations': 'public failure'}
    (tmp_path / 'feedback-messages.json').write_text(json.dumps([
        {'role': 'system', 'content': ''},
        {'role': 'user', 'content': json.dumps({'public_check_feedback': feedback})}]), encoding='utf-8')
    assert compare.shared_payload(tmp_path) == feedback
