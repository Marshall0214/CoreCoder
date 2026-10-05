import json

import pytest

from corecoder.llm import LLMResponse, ToolCall
from evals.runtime import Events
from evals.schema import RunConfig
from evals.symbol_patch import public_requirements, run_symbol_patch


class FakeLLM:
    def __init__(self, response, mutate=None):
        self.response, self.mutate, self.calls = response, mutate, []

    def chat(self, messages, tools):
        self.calls.append((messages, tools))
        if self.mutate:
            self.mutate()
        return self.response


def invoke(tmp_path, response, mutate=None, query='envvar', policy='baseline'):
    (tmp_path / 'entry.py').write_bytes(b'secret = 1\r\ndef envvar(value):\r\n    return value\r\n')
    llm = FakeLLM(response, mutate)
    result = run_symbol_patch(llm, tmp_path, query, ['entry.py'],
                              RunConfig(mode='live', evidence_dependency_depth=1),
                              Events(tmp_path / 'trace.jsonl', 'symbol'), prompt_policy=policy)
    return result, llm


def test_single_request_preserves_fragment_metadata_and_crlf(tmp_path):
    response = LLMResponse(content=json.dumps({'edits': [{'file': 'entry.py', 'old': 'return value', 'new': 'return bool(value)'}]}))
    result, llm = invoke(tmp_path, response)
    assert result['status'] == 'completed' and result['edited_files'] == ['entry.py']
    assert len(llm.calls) == 1 and llm.calls[0][1] == []
    payload = json.loads(llm.calls[0][0][1]['content'])
    assert set(payload) == {'description', 'allowed_files', 'fragments'}
    assert payload['fragments'][0]['complete_symbol']
    assert payload['fragments'][0]['start_line'] == 2
    assert 'secret' not in payload['fragments'][0]['content']
    assert (tmp_path / 'entry.py').read_bytes() == b'secret = 1\r\ndef envvar(value):\r\n    return bool(value)\r\n'


@pytest.mark.parametrize('content', [
    'not json',
    json.dumps({'edits': [{'file': 'entry.py', 'old': 'return value', 'new': 'return 0'},
                          {'file': 'entry.py', 'old': 'secret = 1', 'new': 'secret = 2'}]}),
    json.dumps({'edits': [{'file': '../outside.py', 'old': 'return value', 'new': 'return 0'}]}),
])
def test_invalid_patch_never_writes_any_edit(tmp_path, content):
    result, _ = invoke(tmp_path, LLMResponse(content=content))
    assert result['status'] == 'invalid_patch'
    assert (tmp_path / 'entry.py').read_bytes() == b'secret = 1\r\ndef envvar(value):\r\n    return value\r\n'


def test_source_changed_during_model_call_is_rejected(tmp_path):
    changed = b'secret = 2\r\ndef envvar(value):\r\n    return value\r\n'
    patch = json.dumps({'edits': [{'file': 'entry.py', 'old': 'return value', 'new': 'return 0'}]})
    result, _ = invoke(tmp_path, LLMResponse(content=patch), lambda: (tmp_path / 'entry.py').write_bytes(changed))
    assert result['status'] == 'invalid_patch' and 'version changed' in result['error']
    assert (tmp_path / 'entry.py').read_bytes() == changed


def test_tool_calls_rejected_and_empty_evidence_skips_model(tmp_path):
    result, _ = invoke(tmp_path, LLMResponse(content='{"edits": []}', tool_calls=[ToolCall('id', 'bash', {})]))
    assert result['status'] == 'invalid_patch'
    result, llm = invoke(tmp_path, LLMResponse(content='unused'), query='zzzzunmatched')
    assert result['status'] == 'no_evidence' and not llm.calls


def test_empty_patch_is_completed_without_claiming_verification(tmp_path):
    result, llm = invoke(tmp_path, LLMResponse(content='{"edits": []}'))
    assert result['status'] == 'completed' and result['edited_files'] == []
    assert 'accepted' not in result and 'verification' not in result
    assert len(llm.calls) == 1


def test_behavior_check_uses_verbatim_public_requirements_and_same_evidence(tmp_path):
    query = 'envvar must preserve false values.  Whitespace is false!\nPreserve conversion'
    base, base_llm = invoke(tmp_path, LLMResponse(content='{"edits": []}'), query=query)
    variant, llm = invoke(tmp_path, LLMResponse(content='{"edits": []}'), query=query, policy='behavior-check')
    data = json.loads(llm.calls[0][0][1]['content'])
    baseline = json.loads(base_llm.calls[0][0][1]['content'])
    assert data['fragments'] == baseline['fragments']
    assert variant['evidence_hash'] == base['evidence_hash']
    assert variant['prompt_hash'] != base['prompt_hash']
    assert len(llm.calls) == 1 and set(data) == set(baseline) | {'public_requirements'}
    assert len(data['public_requirements']) == 3
    for row in data['public_requirements']:
        a, b = row['span']
        assert query[a:b] == row['text']
    assert 'accepted' not in variant


def test_requirements_and_prompt_policy_validation(tmp_path):
    assert public_requirements('  \n') == []
    assert [row['text'] for row in public_requirements('First requirement\nSecond requirement')] == [
        'First requirement', 'Second requirement']
    with pytest.raises(ValueError, match='prompt policy'):
        invoke(tmp_path, LLMResponse(content='unused'), policy='unknown')


def test_linked_context_is_optional_and_cannot_enable_feedback(tmp_path):
    llm = FakeLLM(LLMResponse(content='{"edits": []}'))
    (tmp_path / 'entry.py').write_text('def envvar(value):\n    return value\n')
    events = Events(tmp_path / 'linked.jsonl', 'linked')
    result = run_symbol_patch(llm, tmp_path, 'envvar', ['entry.py'], RunConfig(mode='live'), events,
                              context_policy='linked')
    assert result['status'] == 'completed' and result['protocol'] == 'symbol-linked-patch-development-v1'
    assert result['context_policy'] == 'linked' and len(llm.calls) == 1
    with pytest.raises(ValueError, match='single-patch'):
        run_symbol_patch(llm, tmp_path, 'envvar', ['entry.py'], RunConfig(mode='live'), events,
                          context_policy='linked', feedback={})
