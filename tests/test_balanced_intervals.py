import hashlib
import json

import pytest

from corecoder.llm import LLMResponse
from docs.experiments.balanced_interval_live_v1 import patch
from docs.experiments.balanced_intervals_v1 import balanced_evidence
from evals.runtime import BudgetLLM, Events
from evals.symbol_context import apply_symbol_patch
from tests.test_staged_repair import Provider
from tests.test_staged_replay import setup_checkpoint


def row(raw, start, end):
    return {'path':'entry.py', 'content_hash':hashlib.sha256(raw).hexdigest(), 'start_line':start, 'end_line':end,
            'content':'\n'.join(raw.decode().splitlines()[start-1:end]), 'reason':'test'}


def test_balanced_selection_exposes_two_apis_without_inventing_source(tmp_path):
    raw = b'def first():\n    """Keep this documentation."""\n    return 1\ndef second():\n    return 2\n'
    rows = [row(raw, 1, 5)]
    evidence, metadata = balanced_evidence(rows, [], {'entry.py':raw}, 'first and second', 100, ('first','second'))
    assert metadata['content_chars'] == sum(len(r['content']) for r in evidence) <= 100
    assert {a['name'] for a in metadata['definition_coverage']} == {'first','second'}
    assert 'Keep this documentation.' in '\n'.join(r['content'] for r in evidence)
    lines=raw.decode().splitlines()
    for r in evidence:
        assert r['content']=='\n'.join(lines[r['start_line']-1:r['end_line']])


def test_candidate_gap_never_becomes_editable_contiguous_text(tmp_path):
    raw = b'def first():\n    one()\n    secret_gap()\n    two()\n'
    evidence, _ = balanced_evidence([row(raw,1,2),row(raw,4,4)], [], {'entry.py':raw}, 'first', 1000, ('first',))
    assert [(r['start_line'],r['end_line']) for r in evidence] == [(1,2),(4,4)]
    (tmp_path/'entry.py').write_bytes(raw)
    edits=json.dumps({'edits':[{'file':'entry.py','old':'    one()\n    two()','new':'pass'}]})
    with pytest.raises(ValueError, match='not supplied'):
        apply_symbol_patch(edits,tmp_path,['entry.py'],evidence)
    assert (tmp_path/'entry.py').read_bytes()==raw


def test_hash_and_content_drift_rejected():
    raw=b'def first():\n    return 1\n'; r=row(raw,1,2); r['content']='fake'
    with pytest.raises(ValueError,match='mismatch'):
        balanced_evidence([r],[],{'entry.py':raw},'first',100,('first',))


def test_long_single_line_and_zero_budget_do_not_overrun():
    raw=('def first():\n    return "'+'x'*1000+'"\n').encode()
    for limit in (0,5,50):
        evidence, m=balanced_evidence([row(raw,1,2)],[],{'entry.py':raw},'first',limit,('first',))
        assert sum(len(r['content']) for r in evidence)<=limit
        assert m['source_lines_added']==0


def test_crlf_unicode_and_fallback_are_source_exact():
    raw='value = "中文"\r\nother = 1\r\n'.encode()
    r=row(raw,1,2);r['content']=raw.decode()
    evidence,_=balanced_evidence([r],[],{'entry.py':raw},'Repair conversion.',100)
    assert evidence[0]['content']=='value = "中文"\nother = 1'
    assert evidence[0]['content_hash']==hashlib.sha256(raw).hexdigest()


def test_live_adapter_changes_only_evidence_and_keeps_costs(tmp_path):
    source,config,checkpoint=setup_checkpoint(tmp_path)
    payloads=[]
    for policy in ('read-first','public-balanced-v1'):
        provider=Provider([LLMResponse(content='{"edits":[]}')])
        events=Events(tmp_path/f'{policy}.jsonl',policy)
        llm=BudgetLLM(provider,config,events)
        result=patch(llm,source,checkpoint,config,events,policy,('envvar',))
        assert llm.config is config
        assert result['status']=='completed' and llm.calls==1
        assert result['budget_accounting']['pipeline_equivalent_tokens']==360
        payloads.append(json.loads(provider.requests[0][0][1]['content']))
    assert payloads[0].pop('fragments')!=payloads[1].pop('fragments')
    assert payloads[0]==payloads[1]

def test_small_budget_can_cover_both_public_api_headers():
    raw=('def first(public_suffix):\n'+''.join('    # keep original comment\n' for _ in range(30))+'    return public_suffix\n'+'def second(public_suffix):\n'+''.join('    # keep original comment\n' for _ in range(30))+'    return public_suffix\n').encode()
    rows=[row(raw,1,32),row(raw,33,64)]
    evidence,metadata=balanced_evidence(rows,[],{'entry.py':raw},'first and second preserve public_suffix',650,('first','second'))
    assert all(a['visible_lines']>0 for a in metadata['definition_coverage'])
    assert any(not a['complete'] for a in metadata['definition_coverage'])
    assert sum(len(r['content']) for r in evidence)<=650
    assert balanced_evidence(rows,[],{'entry.py':raw},'first and second preserve public_suffix',650,('first','second'))==(evidence,metadata)


def test_shared_localization_cost_is_counted_once_in_analysis(tmp_path,monkeypatch):
    from docs.experiments import balanced_interval_analysis_v1 as analysis
    shared={'checkpoint_hash':'same','localization_tokens':100}
    report={'protocol':{'checkpoints':{'baseline':shared,'balanced':shared}},'pipeline_tokens':240,
            'patch_runs':[{'worker':{'candidate_pool_hash':'pool','packing':None,'evidence_chars':10,'patch_prompt_hash':'a'}},
                          {'worker':{'candidate_pool_hash':'pool','packing':{},'evidence_chars':20,'patch_prompt_hash':'b'}}]}
    (tmp_path/'experiment.json').write_text(json.dumps(report))
    monkeypatch.setattr(analysis,'patch_analysis',lambda root:{'new_patch_tokens':40,'runs':[{},{}]})
    result=analysis.analyze(tmp_path)
    assert result['shared_actual_localization_tokens']==100
    assert result['historical_plus_new_actual_tokens']==140
    assert result['raw_report_branch_pipeline_sum']==240
