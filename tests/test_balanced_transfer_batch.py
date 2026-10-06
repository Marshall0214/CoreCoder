import pytest

from docs.experiments.balanced_transfer_batch_v1 import summarize


def tasks():
    return {'one':{'checkpoints':{'baseline':{'checkpoint_hash':'a','localization_tokens':100},'balanced':{'checkpoint_hash':'a','localization_tokens':100}}},
            'two':{'checkpoints':{'baseline':{'checkpoint_hash':'b','localization_tokens':200},'balanced':{'checkpoint_hash':'b','localization_tokens':200}}}}


def rows():
    return [{'task_id':task,'policy':policy,'accepted':task=='one' and policy=='baseline',
             'status':'passed' if task=='one' and policy=='baseline' else 'invalid_patch',
             'metrics':{'budget_accounted_tokens':10,'llm_calls':1},'worker':{'patch_non_evidence_hash':task}}
            for task in ('one','two') for policy in ('baseline','balanced')]


def test_denominators_include_failed_runs_and_shared_cost_is_not_doubled():
    result=summarize(rows(),tasks())
    assert result['policies']['baseline']['accepted']==1
    assert result['policies']['balanced']['tasks']==2
    assert result['policies']['balanced']['status_counts']=={'invalid_patch':2}
    assert result['actual_new_patch_tokens']==40
    assert result['shared_historical_localization_tokens']==300
    assert result['historical_plus_new_tokens']==340
    assert all(result['matched_non_evidence'].values())


@pytest.mark.parametrize('mutation',['missing','duplicate','unexpected'])
def test_partial_or_duplicate_pairs_cannot_be_complete(mutation):
    runs=rows()
    if mutation=='missing': runs.pop()
    elif mutation=='duplicate': runs[-1]=runs[0]
    else: runs[-1]['task_id']='unknown'
    with pytest.raises(ValueError,match='Missing or duplicated'):
        summarize(runs,tasks())


def test_unknown_usage_and_nonmatching_prompt_remain_visible():
    runs=rows();runs[0]['metrics']=None;runs[0]['worker']={}
    result=summarize(runs,tasks())
    assert result['usage_missing_runs']==1
    assert result['matched_non_evidence']['one'] is False

def test_analysis_retains_regressions_and_rejects_incomplete_results():
    from docs.experiments.balanced_transfer_analysis_v1 import experiment_rows
    from docs.experiments.balanced_transfer_analysis_v1 import summarize as matrix_summary
    runs=rows()
    for run in runs:
        run['artifacts']='artifact'
        run['worker']['candidate_pool_hash']=run['task_id']
    report={'complete':True,'patch_runs':runs,'protocol':{'tasks':tasks(),'task_order':['one','two'],'expected_patch_runs':4}}
    matrix=experiment_rows(report)
    result=matrix_summary(matrix)
    assert result['paired_losses']==['one']
    assert result['policies']['balanced']['tasks']==2
    assert result['historical_plus_new_tokens']==340
    report['complete']=False
    with pytest.raises(ValueError,match='incomplete'):
        experiment_rows(report)


def test_analysis_does_not_merge_the_same_task_twice():
    from docs.experiments.balanced_transfer_analysis_v1 import summarize as matrix_summary
    row={'task_id':'same'}
    with pytest.raises(ValueError,match='twice'):
        matrix_summary([row,row])
