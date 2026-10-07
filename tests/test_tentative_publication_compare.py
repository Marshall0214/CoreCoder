import pytest

from docs.experiments import tentative_publication_compare_v1 as comparison


@pytest.mark.parametrize('stop',['committed','rejected'])
def test_publication_phase_duration_counts_validation_until_terminal(stop):
    events=[{'event':'repair_lifecycle','state':'tentative','time':1},
            {'event':'repair_lifecycle','state':'validating','time':10},
            {'event':'repair_lifecycle','state':stop,'time':12.5}]
    assert comparison.publication_seconds(events)==2.5


@pytest.mark.parametrize('events',[[],[{'event':'repair_lifecycle','state':'rejected','time':10}],
    [{'event':'repair_lifecycle','state':'validating','time':10},{'event':'repair_lifecycle','state':'committed','time':9}]])
def test_unavailable_or_reversed_wall_clock_not_reported_as_zero(events):
    assert comparison.publication_seconds(events) is None


def test_summary_separates_repair_outcome_from_source_protection():
    rows=[]
    for policy,changed in [('direct-write',True),('tentative-publication',False)]:
        rows.append({'task_id':'failed','policy':policy,'accepted':False,'status':'public_check_failed',
                     'process':{'seconds':1.0},'net_source_changed':changed,'publication_seconds':0.5 if not changed else None,
                     'verification':{'regression':{'passed':not changed}},
                     'worker':{'metrics':{'llm_calls':2,'prompt_tokens':100,'completion_tokens':50,
                                         'budget_accounted_tokens':150,'worker_seconds':1.0}}})
    summary=comparison.summarize(rows)
    assert summary['direct-write']['passed']==summary['tentative-publication']['passed']==0
    assert summary['direct-write']['failed_runs_with_source_changes']==1
    assert summary['tentative-publication']['failed_runs_preserving_start']==1
    assert summary['tentative-publication']['publication_seconds']==0.5
