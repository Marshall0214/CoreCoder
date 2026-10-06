import copy
import hashlib
import json

import pytest

from corecoder.llm import LLMResponse
from evals.context_policy import duplicate_read_view, request_breakdown, windowed_read_view
from evals.read_policy import BoundedReadTool
from evals.runtime import BudgetExceeded, BudgetLLM, Events, make_tools
from evals.schema import RunConfig
from evals.worker import TracedLLM


class Recorder:
    model = 'fake'

    def __init__(self, response=None):
        self.calls = []
        self.response = response or LLMResponse(content='done', prompt_tokens=20, completion_tokens=10)

    def chat(self, messages, tools=None, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_remaining_policy_can_use_budget_rejected_by_fixed_policy(tmp_path):
    messages = [{'role': 'user', 'content': 'small request'}]
    estimate = request_breakdown(messages, None)['request_estimate']
    for policy, allowed in [('fixed', False), ('remaining', True)]:
        inner = Recorder()
        config = RunConfig(token_budget=estimate + 300, output_policy=policy)
        llm = BudgetLLM(inner, config, Events(tmp_path / policy, policy))
        if allowed:
            llm.chat(messages)
            assert inner.calls == [{'max_tokens': 300}]
        else:
            with pytest.raises(BudgetExceeded):
                llm.chat(messages)
            assert not inner.calls


def test_remaining_policy_blocks_unusable_response_and_checks_actual_usage(tmp_path):
    messages = [{'role': 'user', 'content': 'small request'}]
    estimate = request_breakdown(messages, None)['request_estimate']
    inner = Recorder()
    llm = BudgetLLM(inner, RunConfig(token_budget=estimate + 255, output_policy='remaining'),
                    Events(tmp_path / 'small', 'small'))
    with pytest.raises(BudgetExceeded):
        llm.chat(messages)
    assert not inner.calls
    inner = Recorder(LLMResponse(content='overrun', prompt_tokens=600, completion_tokens=10))
    llm = BudgetLLM(inner, RunConfig(token_budget=500, output_policy='remaining'),
                    Events(tmp_path / 'overrun', 'overrun'))
    with pytest.raises(BudgetExceeded, match='Returned usage'):
        llm.chat(messages)


def test_remaining_policy_missing_usage_reserves_actual_output_limit(tmp_path):
    messages = [{'role': 'user', 'content': 'small request'}]
    estimate = request_breakdown(messages, None)['request_estimate']
    inner = Recorder(LLMResponse(content='unknown'))
    llm = BudgetLLM(inner, RunConfig(token_budget=estimate + 300, output_policy='remaining'),
                    Events(tmp_path / 'trace', 'test'))
    llm.chat(messages)
    assert llm.spent == estimate + 300
    assert llm.metrics()['missing_usage_calls'] == 1


def test_remaining_policy_also_limits_output_by_context_space(tmp_path):
    messages = [{'role': 'user', 'content': 'x' * 1360}]
    estimate = request_breakdown(messages, None)['request_estimate']
    inner = Recorder()
    llm = BudgetLLM(inner, RunConfig(token_budget=5000, context_tokens=900,
                                   max_output_tokens=512, output_policy='remaining'),
                    Events(tmp_path / 'trace', 'test'))
    llm.chat(messages)
    assert inner.calls == [{'max_tokens': 900 - estimate}]


def test_traced_request_output_limit_is_scoped_and_restored(monkeypatch, tmp_path):
    observed = []
    monkeypatch.setattr('corecoder.llm.LLM.chat', lambda self, messages, **kwargs: observed.append(dict(self.extra)))
    llm = TracedLLM('fake', 'fake', 'http://localhost:11434/v1',
                    events=Events(tmp_path / 'trace', 'test'), max_tokens=2048)
    llm.chat([], max_tokens=300, response_format={'type': 'json_object'})
    llm.chat([])
    assert observed == [{'max_tokens': 300, 'response_format': {'type': 'json_object'}}, {'max_tokens': 2048}]


def test_bounded_read_caps_explicit_large_reads_and_announces_continuation(tmp_path):
    source = tmp_path / 'source.py'
    source.write_text('\n'.join(f'line_{i} = {i}' for i in range(400)))
    tool = BoundedReadTool()
    for kwargs in ({}, {'limit': 2000}):
        result = tool.execute(str(source), **kwargs)
        assert result.startswith('1\tline_0 = 0')
        assert '120\tline_119 = 119' in result
        assert '121\tline_120' not in result
        assert 'next offset 121' in result
    assert tool.execute(str(source), offset=121, limit=2).startswith('121\tline_120')
    source.write_text('x' * 20000)
    result = tool.execute(str(source))
    assert len(result) <= 6000 and 'line truncated' in result


def test_duplicate_view_retains_anchor_and_restores_after_edit_or_anchor_loss(tmp_path):
    source = tmp_path / 'source.py'
    source.write_text('source fragment ' * 100)
    content = '1\t' + 'source fragment ' * 100
    messages = []
    for call_id in ('first', 'again'):
        messages += [{'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {
            'name': 'read_file', 'arguments': json.dumps({'file_path': 'source.py'})}}]},
                     {'role': 'tool', 'tool_call_id': call_id, 'content': content}]
    receipts = [{'path': 'source.py', 'content_hash': hashlib.sha256(source.read_bytes()).hexdigest(),
                 'response': content}]
    original = copy.deepcopy(messages)
    view, stats = duplicate_read_view(messages, tmp_path, receipts)
    assert messages == original and view[1] == messages[1]
    assert 'retained read_file call first' in view[3]['content']
    assert stats['replaced_reads'] == 1 and stats['estimated_input_reduction'] > 0
    assert duplicate_read_view(messages[2:], tmp_path, receipts)[0] == messages[2:]
    source.write_text('x = 2\n')
    assert duplicate_read_view(messages, tmp_path, receipts)[0] == messages


def test_duplicate_view_does_not_merge_equal_text_from_different_files(tmp_path):
    messages, receipts = [], []
    content = '1\t' + 'same fragment ' * 100
    for name in ('one.py', 'two.py'):
        path = tmp_path / name
        path.write_text('same fragment ' * 100)
        messages += [{'role': 'assistant', 'tool_calls': [{'id': name, 'function': {
            'name': 'read_file', 'arguments': json.dumps({'file_path': name})}}]},
                     {'role': 'tool', 'tool_call_id': name, 'content': content}]
        receipts.append({'path': name, 'content_hash': hashlib.sha256(path.read_bytes()).hexdigest(),
                         'response': content})
    assert duplicate_read_view(messages, tmp_path, receipts)[0] == messages


def test_bounded_tools_create_partial_receipts_without_claiming_full_coverage(tmp_path):
    source = tmp_path / 'source.py'
    source.write_text('\n'.join('x = 1' for _ in range(300)))
    tools = make_tools(tmp_path, ['source.py'], Events(tmp_path / 'trace', 'test'), 5,
                       RunConfig(read_policy='bounded'))
    read = next(tool for tool in tools if tool.name == 'read_file')
    read.execute(file_path='source.py')
    assert not read.read_receipts
    assert read.fragment_receipts and not read.fragment_receipts[0]['full_read']


def test_read_window_keeps_recent_fragments_and_labels_omitted_evidence():
    messages = []
    for call_id in ('old', 'recent'):
        messages += [{'role': 'assistant', 'tool_calls': [{'id': call_id, 'function': {
            'name': 'read_file', 'arguments': json.dumps({'file_path': 'code.py', 'offset': 120})}}]},
                     {'role': 'tool', 'tool_call_id': call_id, 'content': call_id * 500}]
    original = copy.deepcopy(messages)
    view, stats = windowed_read_view(messages, max_chars=3500)
    assert messages == original and view[-1] == messages[-1]
    assert 'not retained evidence' in view[1]['content'] and 'offset=120' in view[1]['content']
    assert stats['omitted_reads'] == 1 and stats['retained_read_chars'] == 3000
    assert stats['estimated_input_reduction'] > 0


def test_read_window_reports_small_reads_kept_when_notice_is_more_expensive():
    messages = [{'role': 'assistant', 'tool_calls': [{'id': 'tiny', 'function': {
        'name': 'read_file', 'arguments': json.dumps({'file_path': 'empty.py'})}}]},
                {'role': 'tool', 'tool_call_id': 'tiny', 'content': '(empty file)'}]
    view, stats = windowed_read_view(messages, max_chars=0)
    assert view == messages
    assert stats['unprofitable_reads'] == 1
    assert stats['retained_read_chars'] == len('(empty file)')
