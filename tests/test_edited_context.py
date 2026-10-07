import json
from types import SimpleNamespace

import pytest

from docs.experiments import edited_context_v1 as retention
from docs.experiments import edited_context_worker_v1 as worker
from docs.experiments import function_index_audit_v1 as functions
from evals.runtime import Events


def bundle(root, source='def first():\n    return 1\n\ndef second():\n    return 2\n'):
    (root/'app.py').write_text(source,encoding='utf-8')
    index = functions.FunctionIndex(root,['app.py'])
    index.refresh()
    return functions.pack(index,index.rank('first second'))


def test_committed_edits_only_and_noops(tmp_path):
    base = bundle(tmp_path)
    response = json.dumps({'edits':[{'file':'app.py','old':'return 1','new':'return 3'},
                                    {'file':'app.py','old':'return 2','new':'return 2'}]})
    assert retention.edited_symbols(response,base['evidence'],{'accepted':False}) == []
    assert retention.edited_symbols(response,base['evidence'],{'accepted':True,'changed_files':[]}) == []
    assert retention.edited_symbols(response,base['evidence'],{'accepted':True,'changed_files':['app.py']}) == [{'path':'app.py','symbol':'first'}]


def test_refresh_current_version_prioritize_and_deduplicate(tmp_path):
    base = bundle(tmp_path)
    old_hash = base['evidence'][0]['content_hash']
    current = bundle(tmp_path,'def first():\n    return 3\n\ndef second():\n    return 2\n')
    current['evidence'] = [r for r in current['evidence'] if r['symbol']=='second']
    before = (tmp_path/'app.py').read_bytes()
    result = retention.pack(tmp_path,['app.py'],current,[{'path':'app.py','symbol':'first'}]*2)
    assert [r['symbol'] for r in result['evidence']] == ['first','second']
    assert 'return 3' in result['evidence'][0]['content']
    assert result['evidence'][0]['content_hash'] != old_hash
    assert result['metadata']['combined_chars'] <= 6000
    assert (tmp_path/'app.py').read_bytes() == before


@pytest.mark.parametrize('symbol',['missing','renamed'])
def test_missing_anchor_stops(tmp_path,symbol):
    base = bundle(tmp_path)
    with pytest.raises(retention.ContextUnavailable,match='missing'):
        retention.pack(tmp_path,['app.py'],base,[{'path':'app.py','symbol':symbol}])


def test_mandatory_budget_failure_no_truncation(tmp_path):
    base = bundle(tmp_path)
    with pytest.raises(retention.ContextUnavailable,match='budget'):
        retention.pack(tmp_path,['app.py'],base,[{'path':'app.py','symbol':'first'}],limit=10)


def test_mandatory_seed_limit_failure(tmp_path):
    base = bundle(tmp_path)
    with pytest.raises(retention.ContextUnavailable,match='Too many'):
        retention.pack(tmp_path,['app.py'],base,[{'path':'app.py','symbol':'first'},{'path':'app.py','symbol':'second'}],top_k=1)


def test_optional_rows_displaced_under_same_limit(tmp_path):
    base = bundle(tmp_path)
    base.update(source_contract_facts='abc')
    result = retention.pack(tmp_path,['app.py'],base,[{'path':'app.py','symbol':'second'}],top_k=1)
    assert [r['symbol'] for r in result['evidence']] == ['second']
    assert result['metadata']['combined_chars'] == len(result['evidence'][0]['content'])+5
    assert any(r['reason']=='seed_limit' for r in result['metadata']['discarded'])


def test_stale_optional_evidence_rejected(tmp_path):
    base = bundle(tmp_path)
    (tmp_path/'app.py').write_text('def first():\n    return 8\n\ndef second():\n    return 2\n',encoding='utf-8')
    with pytest.raises(ValueError):
        retention.pack(tmp_path,['app.py'],base,[])


def test_mapping_ambiguous_anchor_rejected(tmp_path):
    base = bundle(tmp_path)
    row = next(r for r in base['evidence'] if r['symbol']=='first')
    response = json.dumps({'edits':[{'file':'app.py','old':'return 1','new':'return 3'}]})
    with pytest.raises(retention.ContextUnavailable,match='ambiguous'):
        retention.edited_symbols(response,[row,dict(row,symbol='other')],{'accepted':True,'changed_files':['app.py']})


@pytest.mark.parametrize('stage',['initial','feedback'])
def test_editor_and_model_share_exact_evidence(tmp_path,monkeypatch,stage):
    workspace = tmp_path/'workspace'
    workspace.mkdir()
    base = bundle(workspace)
    events = Events(tmp_path/'trace.jsonl','retention-test')
    seen = {}
    class LLM:
        def chat(self,messages,tools):
            seen['model'] = json.loads(messages[1]['content'])['fragments']
            assert tools == []
            return SimpleNamespace(content=json.dumps({'edits':[]}),tool_calls=[])
    def transact(response,root,allowed,evidence,*args):
        seen['editor'] = evidence
        return {'accepted':True,'changed_files':[]}
    monkeypatch.setattr(worker.guard,'transact',transact)
    data = {'task_id':'other','allowed_files':['app.py'],'description':'first', 'context_policy':'source-contract',
            'retention_policy':'edited-first','retained_symbols':[{'path':'app.py','symbol':'second'}],
            'test_python':'unused','imports':[]}
    result = worker.request_guarded(LLM(),workspace,data,base['evidence'],events,stage)
    assert seen['model'] == [{k:r.get(k) for k in ('path','start_line','end_line','content_hash','content','symbol')} for r in seen['editor']]
    assert result['edited_symbols'] == []
    if stage=='initial':
        assert seen['editor'] == base['evidence']
    else:
        assert seen['editor'][0]['symbol']=='second'


def test_initial_prompt_equal_between_policies(tmp_path,monkeypatch):
    root=tmp_path/'workspace'; root.mkdir()
    base=bundle(root)
    hashes=[]
    class LLM:
        def chat(self,messages,tools):
            return SimpleNamespace(content='{"edits":[]}',tool_calls=[])
    monkeypatch.setattr(worker.guard,'transact',lambda *args:{'accepted':True,'changed_files':[]})
    for policy in ('baseline','edited-first'):
        folder=tmp_path/policy; folder.mkdir()
        data={'task_id':'other','allowed_files':['app.py'],'description':'first','context_policy':'source-contract',
              'retention_policy':policy,'test_python':'unused','imports':[]}
        result=worker.request_guarded(LLM(),root,data,base['evidence'],Events(folder/'trace.jsonl',policy),'initial')
        hashes.append(result['prompt_hash'])
    assert hashes[0]==hashes[1]
