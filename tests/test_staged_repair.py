import hashlib
import json

import pytest

from corecoder.llm import LLMResponse, ToolCall
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.schema import RunConfig
from evals.staged_repair import pack_fragments, read_fragments, run_staged


class Provider:
    model = 'fake'

    def __init__(self, turns):
        self.turns = iter(turns)
        self.requests = []

    def chat(self, messages, tools=None, **kwargs):
        self.requests.append((messages, tools, kwargs))
        answer = next(self.turns)
        if isinstance(answer, Exception):
            raise answer
        answer.prompt_tokens, answer.completion_tokens = 100, 20
        return answer


def invoke(tmp_path, turns):
    source = tmp_path / 'entry.py'
    source.write_text('def envvar(value):\n    return value\n', encoding='utf-8')
    config = RunConfig(mode='live', token_budget=10000)
    events = Events(tmp_path / 'trace.jsonl', 'staged')
    provider = Provider(turns)
    llm = BudgetLLM(provider, config, events)
    checks = []

    def verify(logs):
        checks.append((logs, source.read_text()))
        return {'passed': True}

    result = run_staged(llm, tmp_path, 'envvar', ['entry.py'], config, events, verify)
    assert llm.config is config
    return result, provider, checks


def test_read_only_localization_then_scoped_patch_and_public_check(tmp_path):
    forbidden = LLMResponse(tool_calls=[ToolCall('bad', 'edit_file', {
        'file_path': 'entry.py', 'old_string': 'return value', 'new_string': 'return 99'})])
    patch = json.dumps({'edits': [{'file': 'entry.py', 'old': 'return value', 'new': 'return bool(value)'}]})
    result, provider, checks = invoke(tmp_path, [forbidden, LLMResponse(content='located'), LLMResponse(content=patch)])
    assert result['status'] == 'completed' and result['edited_files'] == ['entry.py']
    assert result['stage_limits'] == {'explore': 4000, 'patch': 5000, 'verification_reserve': 1000}
    assert all(tool['function']['name'] in {'read_file', 'grep', 'glob'} for tool in provider.requests[0][1])
    assert 'permits' in provider.requests[1][0][-2]['content']
    assert provider.requests[-1][1] == []
    payload = json.loads(provider.requests[-1][0][1]['content'])
    assert payload['budget_state']['patch_tokens'] == 5000
    assert len(checks) == 1 and 'return bool(value)' in checks[0][1]
    assert 'return 99' not in checks[0][1]
    assert 'accepted' not in result  # Independent grading belongs to the parent.


@pytest.mark.parametrize('patch', ['not JSON', '{"edits":[{"file":"../outside.py","old":"x","new":"y"}]}'])
def test_invalid_patch_preserves_source_and_still_runs_public_checks(tmp_path, patch):
    result, _, checks = invoke(tmp_path, [LLMResponse(content='located'), LLMResponse(content=patch)])
    assert result['status'] == 'invalid_patch'
    assert len(checks) == 1 and checks[0][1].endswith('    return value\n')


def test_localization_budget_stop_transitions_to_patch(tmp_path):
    result, provider, checks = invoke(tmp_path, [BudgetExceeded('phase stop'), LLMResponse(content='{"edits": []}')])
    assert result['status'] == 'completed'
    assert result['stages'][0]['reason'] == 'localization_budget_exhausted'
    assert len(provider.requests) == 2 and len(checks) == 1


def test_receipts_reject_stale_or_forged_source_and_pack_whole_fragments(tmp_path):
    raw = b'alpha\nbeta\n'
    (tmp_path / 'entry.py').write_bytes(raw)
    receipt = {'path': 'entry.py', 'content_hash': hashlib.sha256(raw).hexdigest(), 'response': '1\talpha\n2\tbeta'}
    rows = read_fragments(tmp_path, ['entry.py'], [receipt])
    assert rows[0]['content'] == 'alpha\nbeta'
    assert pack_fragments(rows + rows, 10) == rows
    assert pack_fragments(rows, 9) == []
    assert read_fragments(tmp_path, ['entry.py'], [{**receipt, 'response': '1\tforged'}]) == []
    (tmp_path / 'entry.py').write_bytes(b'changed')
    assert read_fragments(tmp_path, ['entry.py'], [receipt]) == []
