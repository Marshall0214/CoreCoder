import json

import pytest

from docs.experiments import balanced_crossfile_live_v1 as adapter
from evals.staged_repair import object_hash
from tests.test_definition_patch import fixture as original_fixture


def setup_pair(tmp_path, monkeypatch):
    protocol, checkpoint = original_fixture(tmp_path, monkeypatch)
    protocol['purpose']='balanced-crossfile-patch-development-v1'
    protocol['order']=['baseline','balanced']
    protocol['checkpoints']['balanced']=protocol['checkpoints'].pop('definition')
    monkeypatch.setattr(adapter,'ROOT',tmp_path)
    monkeypatch.setattr(adapter,'DATA',tmp_path)
    monkeypatch.setattr(adapter,'check_code',lambda protocol:None)
    case=({'public_problem':'envvar'}, {},tmp_path/'checks',tmp_path/'admitted',{})
    monkeypatch.setattr(adapter,'admitted_case',lambda *args:case)
    return protocol,checkpoint


def test_crossfile_packing_requires_same_valid_checkpoint(tmp_path,monkeypatch):
    protocol,checkpoint=setup_pair(tmp_path,monkeypatch)
    _,_,pair=adapter.load_inputs(protocol)
    assert pair['baseline']==pair['balanced']==checkpoint


def test_distinct_checkpoint_rejected_despite_identical_config(tmp_path,monkeypatch):
    protocol,checkpoint=setup_pair(tmp_path,monkeypatch)
    checkpoint['localization_result']['audit_note']='new checkpoint'
    checkpoint['checkpoint_hash']=object_hash({k:v for k,v in checkpoint.items() if k!='checkpoint_hash'})
    path=tmp_path/'definition.json';path.write_text(json.dumps(checkpoint))
    protocol['checkpoints']['balanced'].update(sha256=adapter.file_hash(path),checkpoint_hash=checkpoint['checkpoint_hash'])
    with pytest.raises(ValueError,match='one identical checkpoint'):
        adapter.load_inputs(protocol)
