import json
from pathlib import Path

import pytest

from docs.experiments import expanded_admission_v1 as admission
from docs.experiments import expanded_baseline_v1 as baseline


def fixture(tmp_path, layout='.'):
    root=tmp_path/'before'; package=root/layout/'sample';package.mkdir(parents=True)
    (package/'__init__.py').write_text('def value():\n    return 1\n',encoding='utf-8')
    checks=tmp_path/'checks';checks.mkdir()
    (checks/'test_admission.py').write_text(
        'import unittest\nfrom sample import value\nclass Target(unittest.TestCase):\n'
        '    def test_value(self): self.assertEqual(value(),2)\n'
        'class Controls(unittest.TestCase):\n'
        '    def test_nonnegative(self): self.assertGreaterEqual(value(),0)\n',encoding='utf-8')
    case={'before':str(root),'checks':str(checks),'package':'sample','source_root':layout,
          'allowed_files':[str(Path(layout)/'sample/__init__.py').replace('\\','/')]}
    return root,checks,case


@pytest.mark.parametrize('layout',['.','src'])
def test_independent_grading_reproduces_before_and_repair(tmp_path,layout):
    root,checks,case=fixture(tmp_path,layout)
    before=admission.groups(root,checks,'sample',layout,tmp_path/'before-logs')
    assert not before['Target']['passed'] and before['Controls']['passed']
    workspace=tmp_path/'workspace'
    __import__('shutil').copytree(root,workspace)
    (workspace/case['allowed_files'][0]).write_text('def value():\n    return 2\n',encoding='utf-8')
    result_root=tmp_path/'result';result_root.mkdir()
    result=baseline.verify(case,workspace,result_root)
    assert result['passed'] and result['groups']['Target']['tests_run']==1
    assert 'return 1' in (root/case['allowed_files'][0]).read_text()


def test_out_of_scope_patch_is_not_graded_as_success(tmp_path):
    root,_checks,case=fixture(tmp_path)
    workspace=tmp_path/'workspace';__import__('shutil').copytree(root,workspace)
    (workspace/'extra.py').write_text('pass',encoding='utf-8')
    result_root=tmp_path/'result';result_root.mkdir()
    result=baseline.verify(case,workspace,result_root)
    assert not result['passed'] and result['scope_violations']==['extra.py'] and result['groups'] is None


def test_missing_tests_are_not_passed(tmp_path):
    root,checks,_case=fixture(tmp_path)
    (checks/'test_admission.py').write_text('import unittest\n',encoding='utf-8')
    groups=admission.groups(root,checks,'sample','.',tmp_path/'logs')
    assert not any(g['passed'] for g in groups.values())


def test_catalog_unique_pinned_and_split_before_models():
    catalog=json.loads((admission.DATA/'new-candidates.json').read_text())['cases']
    assert len(catalog)==17 and len({c['task_id'] for c in catalog})==17
    assert sum(c['split']=='heldout' for c in catalog)==10
    assert len({c['repo'] for c in catalog})==3
    for case in catalog:
        assert len(case['before_commit'])==len(case['after_commit'])==40
        assert case['changed_source_files']
        compile((admission.DATA/'checks'/case['task_id']/'test_admission.py').read_text(),case['task_id'],'exec')


def test_incomplete_admission_stops_before_inference(tmp_path):
    path=tmp_path/'admission.json';path.write_text(json.dumps({'complete':False,'cases':[]}))
    with pytest.raises(ValueError,match='30 admitted'):baseline.run(path,tmp_path/'out')
    assert not (tmp_path/'out').exists()
