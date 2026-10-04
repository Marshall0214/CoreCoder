import json

from evals.diagnostics import analyze_trace, before_edit_diagnostics


def test_trace_repeats_and_estimates_are_measured_without_token_claims(tmp_path):
    events = [
        {"event": "llm_started", "request_estimate": 100},
        {"event": "tool_finished", "tool": "read_file", "result": "file v1"},
        {"event": "tool_finished", "tool": "read_file", "result": "file v1"},
        {"event": "tool_finished", "tool": "read_file", "result": "file v2"},
        {"event": "search_completed", "reference_hits": 2, "omitted_chars": 23},
        {"event": "llm_started", "request_estimate": 90},
    ]
    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    result = analyze_trace(path)
    assert result["exact_repeat_read_calls"] == 1
    assert result["repeat_read_response_chars"] == 7
    assert result["read_response_chars"] == 21
    assert result["reference_hits"] == 2
    assert result["omitted_chars"] == 23
    assert result["max_request_estimate"] == 100
    assert result["last_request_estimate"] == 90


def test_empty_trace_does_not_invent_estimates(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text("", encoding="utf-8")
    result = analyze_trace(path)
    assert result["first_request_estimate"] is None
    assert result["max_request_estimate"] is None


def test_search_read_overlap_is_path_scoped_and_counts_text_once(tmp_path):
    evidence = {"results": [{"path": "code.py", "content": "x = 1\ny = 2"},
                            {"path": "code.py", "content": "y = 2"}]}
    events = [{"event": "tool_finished", "tool": "search_code", "result": json.dumps(evidence)}]
    for name in ("other.py", "code.py"):
        events.extend([
            {"event": "tool_started", "tool": "read_file", "arguments": {"file_path": name}},
            {"event": "tool_finished", "tool": "read_file", "result": "1\tx = 1\n2\ty = 2"},
        ])
    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    result = analyze_trace(path)
    assert result["reads_containing_prior_search_text"] == 1
    assert result["prior_search_text_chars_in_reads"] == 11


def test_first_edit_attempt_excludes_later_usage_even_when_edit_fails():
    result = before_edit_diagnostics([
        {"event": "llm_started"},
        {"event": "llm_finished", "usage_known": True, "prompt_tokens": 90, "completion_tokens": 10},
        {"event": "tool_started", "tool": "read_file"},
        {"event": "tool_started", "tool": "edit_file"},
        {"event": "tool_finished", "tool": "edit_file", "result": "Error: not matched"},
        {"event": "llm_started"},
        {"event": "llm_finished", "usage_known": True, "prompt_tokens": 190, "completion_tokens": 10},
    ])
    assert result["first_edit_attempted"]
    assert result["llm_calls_before_first_edit_attempt"] == 1
    assert result["tokens_before_first_edit_attempt"] == 100
    assert result["tool_calls_before_first_edit_attempt"] == {"read_file": 1}


def test_no_edit_and_missing_usage_are_not_reported_as_zero_cost():
    result = before_edit_diagnostics([
        {"event": "llm_started"},
        {"event": "llm_finished", "usage_known": False, "prompt_tokens": None, "completion_tokens": None},
        {"event": "llm_started"},
        {"event": "llm_failed"},
        {"event": "budget_blocked", "reason": "cumulative_preflight", "remaining": 10},
    ])
    assert not result["first_edit_attempted"]
    assert result["tokens_before_first_edit_attempt"] is None
    assert result["unknown_usage_calls_before_first_edit_attempt"] == 2
    assert result["budget_blocks"] == [{"reason": "cumulative_preflight", "remaining": 10}]
