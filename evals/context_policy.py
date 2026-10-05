"""Reversible request views: reference only retained, verified full-file reads."""

import copy
import hashlib
import json
from pathlib import Path

from corecoder.context import estimate_tokens


def call_names(messages):
    return {call["id"]: call["function"]["name"] for message in messages
            for call in message.get("tool_calls", [])}


def request_breakdown(messages, tools, response_format=None):
    names, categories = call_names(messages), {}
    for message in messages:
        category = message.get("role", "unknown")
        if category == "tool":
            name = names.get(message.get("tool_call_id"))
            category = name if name in {"search_code", "read_file"} else "other_tool"
        categories[category] = categories.get(category, 0) + estimate_tokens([message])
    schema = max(0, len(json.dumps(tools or [])) // 3)
    result = {"message_estimates": categories, "schema_estimate": schema,
              "request_estimate": sum(categories.values()) + schema}
    if response_format is not None:
        result["response_format_estimate"] = max(0, len(json.dumps(response_format)) // 3)
        result["request_estimate"] += result["response_format_estimate"]
    return result


def covered_search_view(messages, workspace: Path, receipts):
    """Never change canonical history; dropped/edited read evidence restores originals."""
    workspace = workspace.resolve()
    names, reads = call_names(messages), []
    for position, message in enumerate(messages):
        if message.get("role") != "tool" or names.get(message.get("tool_call_id")) != "read_file":
            continue
        for receipt in receipts:
            if receipt["response"] == message.get("content"):
                # The call identity avoids confusing equal text returned from different paths.
                arguments = next((json.loads(call["function"]["arguments"]) for parent in messages
                                  for call in parent.get("tool_calls", [])
                                  if call["id"] == message.get("tool_call_id")), {})
                path = Path(arguments.get("file_path", ""))
                target = (path if path.is_absolute() else workspace / path).resolve()
                if target == workspace / receipt["path"]:
                    reads.append((position, message["tool_call_id"], receipt))
    view, replaced, omitted, unprofitable = copy.deepcopy(messages), 0, 0, 0
    hashes = {}
    for position, message in enumerate(view):
        if message.get("role") != "tool" or names.get(message.get("tool_call_id")) != "search_code":
            continue
        try:
            result = json.loads(message["content"])
        except (ValueError, TypeError):
            continue
        if not isinstance(result, dict) or not isinstance(result.get("results"), list):
            continue
        changed, local_replaced, local_omitted = False, 0, 0
        for item in result["results"]:
            if not item.get("content"):
                continue
            name = item["path"]
            if name not in hashes:
                target = (workspace / name).resolve()
                try:
                    hashes[name] = (hashlib.sha256(target.read_bytes()).hexdigest()
                                    if target.is_relative_to(workspace) and not target.is_symlink() else None)
                except OSError:
                    hashes[name] = None
            for read_position, call_id, receipt in reads:
                if (read_position > position and receipt["path"] == name
                        and receipt["content_hash"] == item["content_hash"] == hashes[name]):
                    # Exact full-read validation occurred at receipt creation. Verify snippet coverage too.
                    lines = receipt["lines"]
                    start, end = item["start_line"] - 1, item["end_line"]
                    full = "\n".join(lines[start:end])
                    if start < 0 or end > len(lines) or not full.startswith(item["content"]):
                        continue
                    local_omitted += len(item["content"])
                    local_replaced += 1
                    changed = True
                    item.update(content="", reference="retained_read_file", reference_tool_call_id=call_id)
                    break
        if changed:
            result["evidence_chars"] = sum(len(item["content"]) for item in result["results"])
            message["content"] = json.dumps(result, ensure_ascii=False)
            if estimate_tokens([message]) < estimate_tokens([messages[position]]):
                omitted += local_omitted
                replaced += local_replaced
            else:
                message["content"] = messages[position]["content"]
                unprofitable += 1
    return view, {"replaced_chunks": replaced, "omitted_chars": omitted,
                  "unprofitable_messages": unprofitable,
                  "estimated_input_reduction": estimate_tokens(messages) - estimate_tokens(view)}
