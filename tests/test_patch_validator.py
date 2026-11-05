"""Controller validator boundaries and baseline-aware diagnostics; no model calls."""
import importlib.metadata
import json

import pytest

from repairflow import patch_validator as validator
from sandbox import runner


def fixture(tmp_path, before, after, extras=None):
    baseline, candidate = tmp_path/'baseline', tmp_path/'candidate'
    for root,text in ((baseline,before),(candidate,after)):
        root.mkdir()
        (root/'code.py').write_text(text,encoding='utf-8')
        for name,body in (extras or {}).items():
            (root/name).write_text(body,encoding='utf-8')
    return baseline,candidate


def scores(total=1):
    return {'tests_run':total,'successful':True,'returncode':0,'timed_out':False,'errors':0,'failures':0,
            'skipped':0,'expected_failures':0,'unexpected_successes':0,'passed':True}


def mock_public(tmp_path,monkeypatch,total=1):
    from repairflow import checks

    public=tmp_path/'public'
    public.mkdir()
    (public/'test_admission.py').write_text('# trusted test metadata',encoding='utf-8')
    monkeypatch.setenv('CORECODER_TEST_BACKEND','docker')
    monkeypatch.setattr(runner,'preflight',lambda:{'backend':'docker','image_id':'fixed'})
    monkeypatch.setattr(checks,'groups',lambda *args:dict.fromkeys(validator.PUBLIC_GROUPS,scores(total)))
    return public


def test_existing_unbound_symbol_is_not_mistaken_for_new_identifier_only(tmp_path):
    before='def f(rows):\n    if rows:\n        pass\n    for key in missing(rows):\n        yield key\n'
    after='def f(rows):\n    if rows:\n        for key in missing(rows):\n            yield key\n    for key in missing(rows):\n        yield key\n'
    base,candidate=fixture(tmp_path,before,after)
    report=validator.validate(base,candidate,['code.py'],tmp_path/'out')
    assert len(report['static']['baseline_findings'])==1
    assert len(report['static']['candidate_findings'])==2
    assert len(report['static']['retained'])==len(report['static']['introduced'])==1
    assert report['static']['retained'][0]['baseline_line']==4
    assert report['warnings'][0]['candidate_lines']==[3,5]
    assert report['accepted'] is None  # Static-only cannot certify repair.


def test_noqa_and_repo_config_cannot_suppress_undefined_names(tmp_path):
    base,candidate=fixture(tmp_path,'def f():\n    return 1\n','def f():\n    return absent  # noqa: F821\n',
                           {'.ruff.toml':'lint.ignore = ["F821"]\n'})
    report=validator.validate(base,candidate,['code.py'],tmp_path/'out')
    assert report['static']['introduced'][0]['code']=='F821'
    assert report['static']['checker']['configuration'].startswith('isolated')


def test_static_success_without_tests_does_not_claim_accepted(tmp_path):
    base,candidate=fixture(tmp_path,'def f(): return 1\n','def f(): return 2\n')
    report=validator.validate(base,candidate,['code.py'],tmp_path/'out')
    assert report['status']=='static_only' and report['accepted'] is None


def test_new_file_and_test_edits_are_rejected(tmp_path):
    base,candidate=fixture(tmp_path,'x=1\n','x=2\n')
    (candidate/'test_bypass.py').write_text('pass\n')
    report=validator.validate(base,candidate,['code.py'],tmp_path/'out')
    assert 'test_bypass.py' in report['scope_violations']
    for name in ('../escape.py','C:/escape.py','test_x.py','tests/x.py','x\\a.py',42):
        assert not validator.permitted(name)


def test_public_zero_tests_cannot_pass_even_when_passed_flag_is_true(tmp_path,monkeypatch):
    base,candidate=fixture(tmp_path,'x=1\n','x=2\n')
    public=mock_public(tmp_path,monkeypatch,total=0)
    report=validator.validate(base,candidate,['code.py'],tmp_path/'out',public,'pkg')
    assert report['status']=='rejected' and report['accepted'] is False
    assert 'public_reproduce_failed' in report['reasons']


def test_duplicate_loop_warning_is_not_an_automatic_semantic_rejection(tmp_path,monkeypatch):
    base,candidate=fixture(tmp_path,'def f(rows): return list(rows)\n',
        'def f(rows, flag=True):\n    if flag:\n        for x in rows:\n            yield x\n'
        '    else:\n        for x in rows:\n            yield x\n')
    public=mock_public(tmp_path,monkeypatch)
    original=candidate.joinpath('code.py').read_bytes()
    report=validator.validate(base,candidate,['code.py'],tmp_path/'out',public,'pkg')
    assert report['accepted'] is True and report['warnings'][0]['blocking'] is False
    assert candidate.joinpath('code.py').read_bytes()==original
    assert report['independent_grading_used'] is False


def test_syntax_repair_is_allowed_when_baseline_was_invalid(tmp_path,monkeypatch):
    base,candidate=fixture(tmp_path,'def f(:\n    pass\n','def f(): return 1\n')
    public=mock_public(tmp_path,monkeypatch)
    report=validator.validate(base,candidate,['code.py'],tmp_path/'out',public,'pkg')
    assert report['accepted'] is True
    assert report['static']['baseline_syntax_unavailable']==['code.py']


def test_candidate_syntax_error_is_rejected_without_execution(tmp_path,monkeypatch):
    base,candidate=fixture(tmp_path,'x=1\n','def f(:\n')
    public=mock_public(tmp_path,monkeypatch)
    report=validator.validate(base,candidate,['code.py'],tmp_path/'out',public,'pkg')
    assert not report['accepted'] and 'syntax_error' in report['reasons']
    assert report['public_checks'] is None


def test_no_host_execution_fallback(tmp_path,monkeypatch):
    base,candidate=fixture(tmp_path,'x=1\n','x=2\n')
    public=mock_public(tmp_path,monkeypatch)
    monkeypatch.setenv('CORECODER_TEST_BACKEND','local')
    report=validator.validate(base,candidate,['code.py'],tmp_path/'out',public,'pkg')
    assert report['status']=='blocked' and not report['accepted']
    assert report['public_checks'] is None


def test_missing_static_checker_blocks_instead_of_reporting_success(tmp_path,monkeypatch):
    base,candidate=fixture(tmp_path,'x=1\n','x=2\n')
    monkeypatch.setattr(validator.importlib.metadata,'version',lambda _:(_ for _ in ()).throw(
        importlib.metadata.PackageNotFoundError('ruff')))
    report=validator.validate(base,candidate,['code.py'],tmp_path/'out')
    assert report['status']=='blocked' and report['accepted'] is False


def test_outputs_inside_inputs_and_reusing_artifacts_are_refused(tmp_path):
    base,candidate=fixture(tmp_path,'x=1\n','x=2\n')
    with pytest.raises(ValueError):
        validator.validate(base,candidate,['code.py'],candidate/'out')
    validator.validate(base,candidate,['code.py'],tmp_path/'out')
    with pytest.raises(FileExistsError):
        validator.validate(base,candidate,['code.py'],tmp_path/'out')


def test_public_export_does_not_include_independent_results(tmp_path):
    from deploy.langfuse.patch_validation import public_rows

    row={'accepted':False,'candidate_static_findings':1,'retained_static_findings':1,
         'introduced_static_findings':0,'public':{},'reasons':['static'],
         'independent':{'Target':'private-test-details'}}
    validator.save(tmp_path/'report.json',{'status':'passed','model_calls':0,'cases':{'case':row}})
    validator.save(tmp_path/'protocol.json',{'source_files':{}})
    exported=public_rows(tmp_path)
    assert 'independent' not in exported['case']
    assert 'private-test-details' not in json.dumps(exported)
