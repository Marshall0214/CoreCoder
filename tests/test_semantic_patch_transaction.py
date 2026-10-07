import hashlib
import json
import sys

import pytest

from docs.experiments import semantic_patch_transaction_v1 as gate

CODE='''import unittest
from pkg import f
class PublicContract(unittest.TestCase):
    def test_value(self):
        self.assertEqual(f(), 2)
'''


def setup(tmp_path,code=CODE):
    root=tmp_path/'workspace'; package=root/'src/pkg'; package.mkdir(parents=True)
    path=package/'__init__.py'; path.write_text('def f():\n    return 1\n',encoding='utf-8')
    canonical=tmp_path/'canonical.py'; canonical.write_text(code,encoding='utf-8')
    harness=tmp_path/'harness'; harness.mkdir(); (harness/'test_admission.py').write_bytes(canonical.read_bytes())
    check=gate.PublicCheck(harness,canonical,hashlib.sha256(canonical.read_bytes()).hexdigest(),
                          gate.observer.public.repair.digest(gate.observer.public.repair.snapshot(harness)),'pkg')
    data=path.read_bytes(); evidence=[{'path':'src/pkg/__init__.py','content':data.decode(),'content_hash':hashlib.sha256(data).hexdigest()}]
    return root,evidence,check


def run(tmp_path,root,evidence,check,new='return 2'):
    patch=json.dumps({'edits':[{'file':'src/pkg/__init__.py','old':'return 1','new':new}]})
    return gate.transact(patch,root,['src/pkg/__init__.py'],evidence,tmp_path/'transaction',sys.executable,
                         [{'module':'pkg','root':'src','path':'src/pkg/__init__.py'}],check)


def test_correct_patch_commits_exact_checked_candidate(tmp_path):
    root,evidence,check=setup(tmp_path)
    result=run(tmp_path,root,evidence,check)
    assert result['accepted'] and result['committed'] and result['public_check']['tests_run']==1
    assert result['original_after_sha256']==result['candidate_sha256']
    assert (root/'src/pkg/__init__.py').read_text()=='def f():\n    return 2\n'


@pytest.mark.parametrize('new',['return 3',"raise TypeError('candidate error')"])
def test_behavior_failure_never_writes_original(tmp_path,monkeypatch,new):
    root,evidence,check=setup(tmp_path); before=gate.structural.files(root)
    monkeypatch.setattr(gate,'_write',lambda *args:pytest.fail('semantic rejection attempted an original-source write'))
    result=run(tmp_path,root,evidence,check,new)
    assert result['reason']=='public_check_failed' and result['structural']['accepted']
    assert result['original_unchanged'] and gate.structural.files(root)==before
    assert (tmp_path/'transaction/public-diagnostic.txt').is_file()


@pytest.mark.parametrize('code',[CODE.replace('self.assertEqual(f(), 2)','self.skipTest("skip")'),
                                 CODE.replace('def test_value','def not_a_test'),
                                 CODE.replace('self.assertEqual(f(), 2)','raise NameError("harness error")')])
def test_inconclusive_or_harness_error_cannot_commit(tmp_path,code):
    root,evidence,check=setup(tmp_path,code)
    if 'not_a_test' in code:
        with pytest.raises(ValueError,match='unique concrete'): run(tmp_path,root,evidence,check)
    else:
        result=run(tmp_path,root,evidence,check)
        assert result['reason']=='public_check_failed' and result['original_unchanged']


def test_invalid_python_stops_before_public_check(tmp_path,monkeypatch):
    root,evidence,check=setup(tmp_path)
    monkeypatch.setattr(gate.observer,'check_public',lambda *args:pytest.fail('unexpected public execution'))
    result=run(tmp_path,root,evidence,check,'return (')
    assert result['reason']=='invalid_python' and result['public_check'] is None and result['original_unchanged']


@pytest.mark.parametrize('target',['canonical','harness'])
def test_changed_public_code_rejected_before_candidate(tmp_path,target):
    root,evidence,check=setup(tmp_path)
    path=check.canonical if target=='canonical' else check.harness/'test_admission.py'
    path.write_text(CODE+'\n# changed',encoding='utf-8')
    with pytest.raises(ValueError,match='changed|exact canonical'): run(tmp_path,root,evidence,check)
    assert not (tmp_path/'transaction').exists()


def test_public_runner_error_preserves_original(tmp_path,monkeypatch):
    root,evidence,check=setup(tmp_path)
    def fail(*args): raise ValueError('source or check mutation')
    monkeypatch.setattr(gate.observer,'check_public',fail)
    result=run(tmp_path,root,evidence,check)
    assert result['reason']=='public_check_error' and result['original_unchanged']


def test_public_pass_with_wrong_test_count_is_rejected(tmp_path,monkeypatch):
    root,evidence,check=setup(tmp_path)
    monkeypatch.setattr(gate.observer,'check_public',lambda *args:({'passed':True,'classification':'passed','tests_run':2},'synthetic count'))
    result=run(tmp_path,root,evidence,check)
    assert result['reason']=='public_test_count_mismatch' and result['original_unchanged']


def test_external_original_change_is_not_overwritten(tmp_path,monkeypatch):
    root,evidence,check=setup(tmp_path); real=gate.observer.check_public
    def check_and_mutate(*args):
        value=real(*args); (root/'src/pkg/__init__.py').write_text('def f():\n    return 99\n',encoding='utf-8'); return value
    monkeypatch.setattr(gate.observer,'check_public',check_and_mutate)
    result=run(tmp_path,root,evidence,check)
    assert result['reason']=='source_changed' and not result['committed']
    assert 'return 99' in (root/'src/pkg/__init__.py').read_text()


def test_checked_candidate_change_is_rejected(tmp_path,monkeypatch):
    root,evidence,check=setup(tmp_path); real=gate.observer.check_public
    def check_and_mutate(stage,*args):
        value=real(stage,*args); (stage/'src/pkg/__init__.py').write_text('def f():\n    return 99\n',encoding='utf-8'); return value
    monkeypatch.setattr(gate.observer,'check_public',check_and_mutate)
    result=run(tmp_path,root,evidence,check)
    assert result['reason']=='candidate_changed' and result['original_unchanged']


def test_partial_commit_failure_restores_original(tmp_path,monkeypatch):
    root,evidence,check=setup(tmp_path)
    def fail(path,data): path.write_bytes(data); raise OSError('partial write')
    monkeypatch.setattr(gate,'_write',fail)
    result=run(tmp_path,root,evidence,check)
    assert result['reason']=='commit_failed' and result['rollback']['restored'] and result['original_unchanged']


def test_output_cannot_overlap_harness(tmp_path):
    root,evidence,check=setup(tmp_path)
    with pytest.raises(ValueError,match='separate'):
        gate.transact('{}',root,['src/pkg/__init__.py'],evidence,check.harness/'output',sys.executable,[],check)
