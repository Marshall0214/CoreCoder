import copy
import json

import pytest

from corecoder.context import estimate_tokens
from corecoder.demo import ScriptedLLM
from corecoder.llm import LLMResponse, ToolCall
from evals.context_policy import covered_search_view, request_breakdown
from evals.runtime import BudgetExceeded, BudgetLLM, Events, make_tools
from evals.schema import RunConfig
from evals.worker import FixtureAgent


def setup_history(tmp_path, read_args=None):
    (tmp_path / "code.py").write_text("# cursor contract\n" + "x = 1\ny = 2\n" * 20, encoding="utf-8")
    events = Events(tmp_path / "trace.jsonl", "test")
    tools = make_tools(tmp_path, ["code.py"], events, 5, RunConfig(search_backend="keyword"))
    search = next(t for t in tools if t.name == "search_code")
    read = next(t for t in tools if t.name == "read_file")
    args = read_args or {"file_path": "code.py"}
    messages = [
        LLMResponse(tool_calls=[ToolCall("s", "search_code", {"query": "cursor"})]).message,
        {"role": "tool", "tool_call_id": "s", "content": search.execute(query="cursor")},
        LLMResponse(tool_calls=[ToolCall("r", "read_file", args)]).message,
        {"role": "tool", "tool_call_id": "r", "content": read.execute(**args)},
    ]
    return messages, read.read_receipts, tools, events


def test_coverage_is_a_reversible_view_with_original_evidence_preserved(tmp_path):
    messages, receipts, _, _ = setup_history(tmp_path)
    original = copy.deepcopy(messages)
    view, stats = covered_search_view(messages, tmp_path, receipts)
    item = json.loads(view[1]["content"])["results"][0]
    assert item["content"] == ""
    assert item["reference_tool_call_id"] == "r"
    assert stats["replaced_chunks"] == 1
    assert messages == original
    without_read, stats = covered_search_view(messages[:2], tmp_path, receipts)
    assert without_read == messages[:2]
    assert stats["replaced_chunks"] == 0


@pytest.mark.parametrize("change", ["file", "snipped_read", "other_path", "deleted"])
def test_invalidated_evidence_keeps_full_search(tmp_path, change):
    messages, receipts, _, _ = setup_history(tmp_path)
    if change == "file":
        (tmp_path / "code.py").write_text("# cursor changed\n", encoding="utf-8")
    elif change == "snipped_read":
        messages[-1]["content"] = "1\t# cursor contract..."
    elif change == "other_path":
        messages[-2]["tool_calls"][0]["function"]["arguments"] = json.dumps({"file_path": "other.py"})
    else:
        (tmp_path / "code.py").unlink()
    view, stats = covered_search_view(messages, tmp_path, receipts)
    assert view == messages
    assert stats["replaced_chunks"] == 0


@pytest.mark.parametrize("args", [{"file_path": "code.py", "limit": 1},
                                  {"file_path": "code.py", "offset": 2},
                                  {"file_path": "missing.py"}])
def test_partial_or_failed_read_cannot_cover(tmp_path, args):
    messages, receipts, _, _ = setup_history(tmp_path, args)
    assert receipts == []
    assert covered_search_view(messages, tmp_path, receipts)[0] == messages


def test_breakdown_matches_existing_estimator_and_blocked_request_is_logged(tmp_path):
    messages, _, _, events = setup_history(tmp_path)
    tools = [{"name": "example"}]
    breakdown = request_breakdown(messages, tools)
    assert breakdown["request_estimate"] == estimate_tokens(messages) + len(json.dumps(tools)) // 3
    assert "search_code" in breakdown["message_estimates"]
    assert "read_file" in breakdown["message_estimates"]
    llm = BudgetLLM(ScriptedLLM([]), RunConfig(token_budget=1), events)
    with pytest.raises(BudgetExceeded):
        llm.chat(messages, tools)
    records = [json.loads(line) for line in events.path.read_text(encoding="utf-8").splitlines()]
    assert records[-2]["event"] == "request_preflight"
    assert records[-1]["reason"] == "cumulative_preflight"
    assert llm.calls == 0


def test_real_agent_request_uses_view_but_keeps_canonical_history(tmp_path):
    _, _, tools, events = setup_history(tmp_path)
    captured = []

    class RecordingLLM(ScriptedLLM):
        def chat(self, messages, **kwargs):
            captured.append(copy.deepcopy(messages))
            return super().chat(messages, **kwargs)

    llm = RecordingLLM([
        LLMResponse(tool_calls=[ToolCall("s", "search_code", {"query": "cursor"})]),
        LLMResponse(tool_calls=[ToolCall("r", "read_file", {"file_path": "code.py"})]),
        LLMResponse(content="done"),
    ])
    agent = FixtureAgent(llm, tools=tools)
    agent.evidence_policy, agent.evidence_workspace, agent.context_events = "read-cover", tmp_path, events
    assert agent.chat("locate cursor") == "done"
    search_view = next(m for m in captured[-1] if m.get("tool_call_id") == "s")
    search_original = next(m for m in agent.messages if m.get("tool_call_id") == "s")
    assert json.loads(search_view["content"])["results"][0]["content"] == ""
    assert json.loads(search_original["content"])["results"][0]["content"]


def test_reference_overhead_does_not_increase_estimated_request(tmp_path):
    messages, receipts, tools, _ = setup_history(tmp_path)
    search = next(t for t in tools if t.name == "search_code")
    read = next(t for t in tools if t.name == "read_file")
    (tmp_path / "code.py").write_text("# cursor\n", encoding="utf-8")
    messages[1]["content"] = search.execute(query="cursor")
    messages[3]["content"] = read.execute(file_path="code.py")
    view, stats = covered_search_view(messages, tmp_path, receipts)
    assert view == messages
    assert stats["unprofitable_messages"] == 1
    assert stats["estimated_input_reduction"] == 0


@pytest.mark.parametrize("backend,history", [("off", "full"), ("none", "full"), ("keyword", "deduplicate")])
def test_read_cover_is_a_separate_keyword_intervention(backend, history):
    with pytest.raises(ValueError):
        RunConfig(search_backend=backend, search_history=history, context_policy="read-cover")
