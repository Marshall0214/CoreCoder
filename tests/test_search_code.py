"""Search scope, evidence accounting, freshness and evaluation integration."""

import json

import pytest

from corecoder.retrieval.keyword import KeywordIndex, terms
from corecoder.tools.search_code import SearchCodeTool
from evals.runner import DEFAULT_SUITE, run_task
from evals.runtime import Events, make_tools
from evals.schema import RunConfig, load_suite


def put(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def test_code_and_markdown_return_valid_relative_citations(tmp_path):
    put(tmp_path, "query.py", "def cursor_after(row):\n    return row['id']\n")
    put(tmp_path, "docs/paging.md", "# Cursor contract\nResume after the last returned row.\n")
    result = json.loads(SearchCodeTool(tmp_path).execute("cursor", 5))
    assert {item["path"] for item in result["results"]} == {"query.py", "docs/paging.md"}
    for item in result["results"]:
        lines = (tmp_path / item["path"]).read_text(encoding="utf-8").splitlines()
        assert item["content"] == "\n".join(lines[item["start_line"] - 1:item["end_line"]])
        assert len(item["content_hash"]) == 64


def test_empty_control_shares_schema_and_response_shape(tmp_path):
    put(tmp_path, "code.py", "# cursor contract\n")
    control = SearchCodeTool(tmp_path, backend="none")
    keyword = SearchCodeTool(tmp_path, backend="keyword")
    assert control.schema() == keyword.schema()
    empty = json.loads(control.execute("cursor"))
    evidence = json.loads(keyword.execute("cursor"))
    assert empty.keys() == evidence.keys()
    assert empty["results"] == [] and empty["evidence_chars"] == 0
    assert empty["index_hash"] == evidence["index_hash"]
    assert evidence["results"]


def test_no_match_does_not_fabricate_evidence(tmp_path):
    put(tmp_path, "code.py", "# cursor\n")
    result = json.loads(SearchCodeTool(tmp_path).execute("unmatchedterm"))
    assert result["results"] == []


def test_scope_excludes_tests_annotations_and_unallowed_sources(tmp_path):
    for path in ("main.py", "other.py", "tests/test_visible.py", "hidden_tests/test_target.py",
                 "_target_tests/test_target.py", ".git/leak.md", ".eval-logs/leak.md"):
        put(tmp_path, path, "# sentinel\n")
    put(tmp_path, "docs/contract.md", "sentinel\n")
    put(tmp_path, "evaluation.json", '{"answer": "sentinel"}')
    result = json.loads(SearchCodeTool(tmp_path, allowed_sources=["main.py"]).execute("sentinel"))
    assert {item["path"] for item in result["results"]} == {"main.py", "docs/contract.md"}


def test_symlink_outside_workspace_is_not_indexed(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = put(tmp_path, "secret.md", "sentinel\n")
    try:
        (root / "linked.md").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks requires additional Windows privileges")
    assert json.loads(SearchCodeTool(root).execute("sentinel"))["results"] == []


def test_edits_additions_and_deletions_refresh_index(tmp_path):
    path = put(tmp_path, "code.py", "# oldterm\n")
    tool = SearchCodeTool(tmp_path)
    initial = json.loads(tool.execute("oldterm"))
    path.write_text("# newterm\n", encoding="utf-8")
    updated = json.loads(tool.execute("newterm"))
    assert initial["index_hash"] != updated["index_hash"]
    assert initial["results"][0]["content_hash"] != updated["results"][0]["content_hash"]
    assert not json.loads(tool.execute("oldterm"))["results"]
    added = put(tmp_path, "docs/new.md", "addedterm\n")
    assert json.loads(tool.execute("addedterm"))["results"]
    added.unlink()
    assert not json.loads(tool.execute("addedterm"))["results"]


def test_fixed_chunks_and_line_numbers(tmp_path):
    put(tmp_path, "code.py", "one\ntwo\nthree\nfour\nfive\n")
    index = KeywordIndex(tmp_path, chunk_lines=2)
    index.refresh()
    assert [(chunk.start_line, chunk.end_line) for chunk in index.chunks] == [(1, 2), (3, 4), (5, 5)]


def test_content_budget_and_truncation_are_explicit(tmp_path):
    put(tmp_path, "code.py", "evidence " * 100)
    result = json.loads(SearchCodeTool(tmp_path, max_chars=256).execute("evidence"))
    assert result["evidence_chars"] == sum(len(item["content"]) for item in result["results"]) <= 256
    assert result["results"][0]["truncated"]


def test_exact_duplicate_evidence_is_not_repeated(tmp_path):
    put(tmp_path, "a.py", "# evidence\n")
    put(tmp_path, "b.py", "# evidence\n")
    assert len(json.loads(SearchCodeTool(tmp_path).execute("evidence"))["results"]) == 1


@pytest.mark.parametrize("query,top_k", [("", 5), ("x" * 1001, 5), ("query", 0), ("query", True)])
def test_invalid_requests_are_rejected(tmp_path, query, top_k):
    with pytest.raises(ValueError):
        SearchCodeTool(tmp_path).execute(query, top_k)


def test_ranking_is_deterministic_and_top_k_bounded(tmp_path):
    put(tmp_path, "a.py", "# cursor\n")
    put(tmp_path, "b.py", "# cursor\n# additional context\n")
    tool = SearchCodeTool(tmp_path)
    assert tool.execute("cursor", 1) == tool.execute("cursor", 1)
    assert len(json.loads(tool.execute("cursor", 1))["results"]) == 1


def test_tokenization_handles_identifiers_and_literal_chinese():
    assert terms("cursorAfter cursor_after") == ["cursor", "after", "cursor", "after"]
    assert terms("分页游标") == ["分页", "页游", "游标"]


def test_trace_records_selection_and_cache_hit(tmp_path):
    put(tmp_path, "code.py", "# evidence\n")
    records = []
    tool = SearchCodeTool(tmp_path, emit=lambda event, **fields: records.append((event, fields)))
    tool.execute("evidence")
    tool.execute("evidence")
    assert records[0][0] == "search_completed"
    assert not records[0][1]["index"]["cache_hit"]
    assert records[1][1]["index"]["cache_hit"]
    assert records[0][1]["selected"][0]["path"] == "code.py"
    assert "content" not in records[0][1]["selected"][0]


def test_original_tools_are_unchanged_without_search(tmp_path):
    events = Events(tmp_path / "trace.jsonl", "test")
    tools = make_tools(tmp_path, [], events, 5, RunConfig())
    assert "search_code" not in {tool.name for tool in tools}
    enabled = make_tools(tmp_path, [], events, 5, RunConfig(search_backend="keyword"))
    assert {tool.name for tool in enabled} == {tool.name for tool in tools} | {"search_code"}


def test_scripted_workers_use_shared_search_protocol(tmp_path):
    task = load_suite(DEFAULT_SUITE / "localization-v1", ["pagination-cursor"])[0]
    reports = [run_task(task, RunConfig(mode="scripted", search_backend=backend), tmp_path)
               for backend in ("none", "keyword")]
    assert all(report["accepted"] for report in reports), reports
    control, keyword = [report["worker"] for report in reports]
    assert control["tool_schema_hash"] == keyword["tool_schema_hash"]
    assert control["protocol_prompt_hash"] == keyword["protocol_prompt_hash"]
    for report in reports:
        events = [json.loads(line) for line in (tmp_path / report["run_id"] / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        searches = [event for event in events if event["event"] == "search_completed"]
        assert len(searches) == 1
        assert searches[0]["index"]["files"] == 8  # seven sources and one contract
        if report["config"]["search_backend"] == "none":
            assert searches[0]["evidence_chars"] == 0
        else:
            assert searches[0]["evidence_chars"] > 0
