import pytest

from docs.experiments import reasoning_provider_v3 as adapter
from docs.experiments.reasoning_repair_compare_v3 import TASKS, trial_config
from docs.experiments.reasoning_repair_report_v3 import audit
from evals.runtime import Events


@pytest.mark.parametrize('policy', ['off', 'on'])
def test_expanded_native_request_and_usage(tmp_path, policy):
    requests = []

    def transport(request):
        requests.append(request)
        return {'model': adapter.calibration.MODEL, 'done': True, 'done_reason': 'stop',
                'prompt_eval_count': 100, 'eval_count': 12000,
                'message': {'content': '{}', 'thinking': 'private' if policy == 'on' else ''}}

    events = Events(tmp_path / 'trace.jsonl', policy)
    llm = adapter.CheckedBudgetLLM(adapter.Provider(policy, events, transport), trial_config(), events)
    llm.chat([{'role': 'user', 'content': 'repair'}])
    request = requests[0]
    assert request['think'] is (policy == 'on')
    assert request['options']['num_ctx'] == trial_config().context_tokens == 40960
    assert request['options']['num_predict'] == 32768
    assert llm.metrics()['budget_accounted_tokens'] == 12100
    assert all('private' not in p.read_text() for p in tmp_path.rglob('*') if p.is_file())


def test_feasibility_pool_and_budget():
    config = trial_config()
    assert len(set(TASKS)) == 6
    assert config.token_budget == 60000
    assert config.max_output_tokens < config.context_tokens
    assert config.wall_timeout == 2700


def test_truncation_is_charged_and_rejected(tmp_path):
    events = Events(tmp_path / 'trace.jsonl', 'on')
    def transport(request):
        return {'model': adapter.calibration.MODEL, 'done': True, 'done_reason': 'length',
                'prompt_eval_count': 100, 'eval_count': 32768,
                'message': {'content': '', 'thinking': 'private'}}
    llm = adapter.CheckedBudgetLLM(adapter.Provider('on', events, transport), trial_config(), events)
    with pytest.raises(adapter.existing.InvalidCompletion, match='output_truncated'):
        llm.chat([{'role': 'user', 'content': 'repair'}])
    assert llm.metrics()['budget_accounted_tokens'] == 32868


def test_report_requires_complete_matching_pairs():
    report = {'complete': True, 'runs': []}
    for task in TASKS:
        for policy in ('off', 'on'):
            report['runs'].append({'task_id': task, 'policy': policy, 'accepted': policy == 'on',
                'verification': {'groups': {}}, 'process': {'seconds': 1},
                'worker': {'status': 'completed', 'seconds': 1, 'metrics': {},
                           'provider_calls': [{'prompt_hash': task, 'finish_reason': 'stop'}]}})
    result = audit(report)
    assert result['gained'] == list(TASKS)
    assert not result['lost']
    report['runs'][0]['worker']['provider_calls'][0]['prompt_hash'] = 'wrong'
    with pytest.raises(ValueError, match='mismatched first prompt'):
        audit(report)
    report['complete'] = False
    with pytest.raises(ValueError, match='twelve unique'):
        audit(report)
