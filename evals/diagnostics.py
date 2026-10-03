"""Read-only trace diagnostics; repeated characters are not saved tokens."""

import argparse
import json
from collections import Counter
from pathlib import Path


def analyze_trace(path: Path) -> dict:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    searches = [event for event in events if event["event"] == "search_completed"]
    estimates = [event["request_estimate"] for event in events if event["event"] == "llm_started"]
    seen, repeats, repeated_chars, read_chars = set(), 0, 0, 0
    evidence, active_read = {}, None
    overlap_reads, overlap_chars = 0, 0
    tools = Counter()
    for event in events:
        if event["event"] == "tool_started" and event["tool"] == "read_file":
            active_read = str(event["arguments"].get("file_path", "")).replace("\\", "/")
        if event["event"] != "tool_finished":
            continue
        tools[event["tool"]] += 1
        if event["tool"] == "search_code":
            try:
                result = json.loads(event["result"])
            except (ValueError, TypeError):
                continue
            for item in result.get("results", []) if isinstance(result, dict) else []:
                if item.get("content"):
                    evidence.setdefault(item["path"], set()).add(item["content"])
        if event["tool"] == "read_file":
            body = event["result"]
            read_chars += len(body)
            if body in seen:
                repeats += 1
                repeated_chars += len(body)
            seen.add(body)
            lines = [line.partition("\t") for line in body.splitlines()]
            if lines and all(number.isdigit() and separator for number, separator, _ in lines):
                source = "\n".join(content for _, _, content in lines)
                # Match exact earlier search snippets for this path, then union their spans.
                covered = set()
                for name, snippets in evidence.items():
                    if active_read != name and not (active_read or "").endswith("/" + name):
                        continue
                    for snippet in snippets:
                        start = source.find(snippet)
                        if start >= 0:
                            covered.update(range(start, start + len(snippet)))
                overlap_reads += bool(covered)
                overlap_chars += len(covered)
            active_read = None
    return {
        "trace": str(path), "tool_calls": dict(tools),
        "search_calls": len(searches),
        "reference_hits": sum(event.get("reference_hits", 0) for event in searches),
        "omitted_chars": sum(event.get("omitted_chars", 0) for event in searches),
        "exact_repeat_read_calls": repeats, "repeat_read_response_chars": repeated_chars,
        "read_response_chars": read_chars, "request_estimates": estimates,
        "reads_containing_prior_search_text": overlap_reads,
        "prior_search_text_chars_in_reads": overlap_chars,
        "first_request_estimate": estimates[0] if estimates else None,
        "last_request_estimate": estimates[-1] if estimates else None,
        "max_request_estimate": max(estimates) if estimates else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    traces = sorted(args.root.rglob("trace.jsonl"))
    if not traces:
        parser.error("No trace.jsonl found")
    runs = [analyze_trace(path) for path in traces]
    result = {
        "scope": "observed exact responses and earlier same-path search text; not retained-history or causal token savings",
        "runs": runs, "run_count": len(runs),
        "reference_run_count": sum(run["reference_hits"] > 0 for run in runs),
        "reference_hits": sum(run["reference_hits"] for run in runs),
        "exact_repeat_read_calls": sum(run["exact_repeat_read_calls"] for run in runs),
        "reads_containing_prior_search_text": sum(run["reads_containing_prior_search_text"] for run in runs),
        "prior_search_text_chars_in_reads": sum(run["prior_search_text_chars_in_reads"] for run in runs),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
