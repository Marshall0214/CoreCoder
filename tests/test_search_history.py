"""Cross-call references are scoped to delivered, current, retained evidence."""

import json

import pytest

from corecoder.demo import ScriptedLLM
from corecoder.llm import LLMResponse, ToolCall
from corecoder.tools.search_code import SearchCodeTool
from evals.runtime import Events, make_tools
from evals.schema import RunConfig
from evals.worker import FixtureAgent


def tool(root, deduplicate=True, max_chars=6000):
    (root / "code.py").write_text("# cursor contract\n" + "# evidence\n" * 30, encoding="utf-8")
    return SearchCodeTool(root, deduplicate_history=deduplicate, max_chars=max_chars)


def test_repeat_returns_reference_and_records_saved_body(tmp_path):
    records = []
    search = tool(tmp_path)
    search.emit = lambda event, **fields: records.append(fields)
    first = json.loads(search.execute("cursor"))
    second = json.loads(search.execute("cursor"))
    assert first["results"][0]["content"]
    assert second["results"][0]["content"] == ""
    assert second["results"][0]["reference"] == "previous_search_result"
    assert records[1]["omitted_chars"] == first["evidence_chars"]
    assert records[1]["reference_hits"] == 1


def test_full_mode_and_schema_are_unchanged(tmp_path):
    search = tool(tmp_path, False)
    assert search.execute("cursor") == search.execute("cursor")
    assert search.schema() == tool(tmp_path).schema()


def test_changed_file_is_returned_in_full(tmp_path):
    search = tool(tmp_path)
    first = json.loads(search.execute("cursor"))
    (tmp_path / "code.py").write_text("# cursor changed\n", encoding="utf-8")
    second = json.loads(search.execute("cursor"))
    assert second["results"][0]["content"] == "# cursor changed"
    assert first["results"][0]["content_hash"] != second["results"][0]["content_hash"]


def test_removed_history_forces_full_evidence_again(tmp_path):
    search = tool(tmp_path)
    first = search.execute("cursor")
    search.sync_history([{"role": "tool", "content": first}])
    assert json.loads(search.execute("cursor"))["results"][0]["content"] == ""
    search.sync_history([{"role": "assistant", "content": "compressed summary"}])
    assert json.loads(search.execute("cursor"))["results"][0]["content"]


def test_reference_alone_does_not_keep_original_alive(tmp_path):
    search = tool(tmp_path)
    search.execute("cursor")
    reference = search.execute("cursor")
    search.sync_history([{"role": "tool", "content": reference}])
    assert json.loads(search.execute("cursor"))["results"][0]["content"]


def test_truncated_snippet_does_not_hide_undelivered_tail(tmp_path):
    search = tool(tmp_path, max_chars=256)
    first = json.loads(search.execute("cursor"))
    assert first["results"][0]["truncated"]
    search.max_chars = 6000
    second = json.loads(search.execute("cursor"))
    assert not second["results"][0]["truncated"]
    assert second["results"][0]["content"]


def test_new_tool_has_no_previous_task_memory(tmp_path):
    search = tool(tmp_path)
    search.execute("cursor")
    assert json.loads(tool(tmp_path).execute("cursor"))["results"][0]["content"]


def test_references_do_not_expand_logical_selection_budget(tmp_path):
    full = tool(tmp_path, False, 256)
    dedup = tool(tmp_path, True, 256)
    (tmp_path / "other.py").write_text("# cursor other\n" * 25, encoding="utf-8")
    baseline = json.loads(full.execute("cursor"))
    dedup.execute("cursor")
    repeated = json.loads(dedup.execute("cursor"))
    assert [(item["path"], item["start_line"], item["end_line"]) for item in baseline["results"]] == [
        (item["path"], item["start_line"], item["end_line"]) for item in repeated["results"]]


@pytest.mark.parametrize("backend", ["off", "none"])
def test_deduplication_requires_keyword(backend):
    with pytest.raises(ValueError):
        RunConfig(search_backend=backend, search_history="deduplicate")


@pytest.mark.parametrize("history", ["full", "deduplicate"])
def test_real_agent_loop_keeps_or_reinjects_evidence(tmp_path, history):
    tool(tmp_path)
    events = Events(tmp_path / "trace.jsonl", "test")
    config = RunConfig(search_backend="keyword", search_history=history)
    tools = make_tools(tmp_path, ["code.py"], events, 5, config)
    script = [LLMResponse(tool_calls=[ToolCall(str(i), "search_code", {"query": "cursor"})]) for i in range(2)]
    script.append(LLMResponse(content="done"))
    agent = FixtureAgent(ScriptedLLM(script), tools=tools)
    assert agent.chat("locate cursor") == "done"
    results = [json.loads(message["content"]) for message in agent.messages if message["role"] == "tool"]
    assert bool(results[1]["results"][0]["content"]) == (history == "full")
    # Simulate compaction dropping original tool messages, then use the same tool instance.
    agent.messages = []
    agent.llm = ScriptedLLM([LLMResponse(tool_calls=[ToolCall("new", "search_code", {"query": "cursor"})]),
                             LLMResponse(content="done")])
    agent.chat("locate cursor again")
    response = next(message for message in agent.messages if message["role"] == "tool")
    assert json.loads(response["content"])["results"][0]["content"]
