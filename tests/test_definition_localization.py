import json

from corecoder.llm import LLMResponse, ToolCall
from docs.experiments.definition_localization_v1 import localize_definition
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.schema import RunConfig
from evals.staged_repair import localize_staged
from tests.test_staged_repair import Provider


def setup(tmp_path, turns):
    (tmp_path / 'entry.py').write_text('def alpha(value):\n    """Keep documentation."""\n    return value\n', encoding='utf-8')
    config = RunConfig(mode='live', token_budget=10000)
    events = Events(tmp_path / 'trace.jsonl', 'definition')
    provider = Provider(turns)
    llm = BudgetLLM(provider, config, events)
    return config, events, provider, llm


def test_baseline_adapter_matches_existing_localizer(tmp_path):
    config, events, provider, llm = setup(tmp_path, [LLMResponse(content='done')])
    baseline = localize_staged(llm, tmp_path, 'alpha defect', ['entry.py'], config, events)
    config, events, other, llm = setup(tmp_path, [LLMResponse(content='done')])
    adapted = localize_definition(llm, tmp_path, 'alpha defect', ['entry.py'], config, events, 'baseline')
    assert provider.requests == other.requests
    assert baseline['pool'] == adapted['pool']
    assert baseline['localization_result']['stage_limits'] == adapted['localization_result']['stage_limits']


def test_definition_is_optional_and_receipts_enter_validated_pool(tmp_path):
    turns = [LLMResponse(tool_calls=[ToolCall('read', 'read_definition', {'file_path': 'entry.py', 'symbol': 'alpha'})]), LLMResponse(content='done')]
    config, events, provider, llm = setup(tmp_path, turns)
    result = localize_definition(llm, tmp_path, 'alpha defect', ['entry.py'], config, events, 'definition')
    assert llm.config is config
    assert {t['function']['name'] for t in provider.requests[0][1]} == {'read_file', 'grep', 'glob', 'read_definition'}
    response = json.loads(provider.requests[1][0][-2]['content'])
    assert response['complete_symbol'] and response['shown_range'] == [1, 3]
    assert result['pool']['reads'][0]['end_line'] == 3
    assert 'Keep documentation' in result['pool']['reads'][0]['content']
    assert 'definition_read' in events.path.read_text()


def test_forbidden_edit_and_budget_stop_preserve_source(tmp_path):
    turns = [LLMResponse(tool_calls=[ToolCall('edit', 'edit_file', {'file_path': 'entry.py', 'old_string': 'return value', 'new_string': 'return 9'})]), BudgetExceeded('stop')]
    config, events, provider, llm = setup(tmp_path, turns)
    result = localize_definition(llm, tmp_path, 'alpha', ['entry.py'], config, events, 'definition')
    assert llm.config is config
    assert 'allowlist' in provider.requests[1][0][-2]['content']
    assert result['localization_result']['stages'][0]['reason'] == 'localization_budget_exhausted'
    assert 'return value' in (tmp_path / 'entry.py').read_text()
    assert result['pool']['reads'] == []
