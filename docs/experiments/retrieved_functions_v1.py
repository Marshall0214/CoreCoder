"""Map frozen BM25 chunks to exact function evidence, without repair labels."""

import ast
import hashlib

from corecoder.retrieval.keyword import KeywordIndex
from evals.symbol_context import dependency_refs, module_name, parse_source


def evidence(workspace, allowed, observation, limit=6000):
    index = KeywordIndex(workspace, allowed)
    if index.refresh()["index_hash"] != observation["index"]["index_hash"]:
        raise ValueError("Frozen retrieval corpus changed")
    originals = {(c.path, c.start_line, c.end_line, c.content_hash): c for c in index.chunks}
    modules = {module_name(path): path for path in allowed}
    parsed = {}
    versions = {c.path: c.content_hash for c in index.chunks}
    for path in sorted(set(allowed) & set(versions)):
        target = workspace / path
        if target.is_symlink() or not target.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("Source path escaped workspace")
        raw = (workspace / path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != versions[path]:
            raise ValueError("Source changed after indexing")
        parsed[path] = parse_source(path, raw, modules)
        parsed[path]["hash"] = hashlib.sha256(raw).hexdigest()
    selected, rejected, dependencies = [], [], []
    seen, used = set(), 0

    def append(path, start, end, content, version, symbol, rank, reason):
        nonlocal used
        key = (path, start, end)
        if key in seen or any(r["path"] == path and r["start_line"] <= start and r["end_line"] >= end for r in selected):
            return False
        seen.add(key)
        if used + len(content) > limit:
            rejected.append({"path": path, "symbol": symbol, "rank": rank, "reason": "budget", "chars": len(content)})
            return False
        selected.append({"path": path, "start_line": start, "end_line": end, "content": content,
                         "content_hash": version, "symbol": symbol, "rank": rank, "reason": reason})
        used += len(content)
        return True

    for rank, row in enumerate(observation["chunk_rankings"]["bm25"], 1):
        if len(selected) >= 5:
            break
        key = tuple(row[k] for k in ("path", "start_line", "end_line", "content_hash"))
        if key not in originals:
            raise ValueError("Frozen chunk citation differs from current source")
        chunk = originals[key]
        info = parsed.get(chunk.path)
        candidates = []
        if info:
            for name, (start, end, node) in info["symbols"].items():
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and start <= chunk.end_line and end >= chunk.start_line:
                    overlap = min(end, chunk.end_line) - max(start, chunk.start_line) + 1
                    candidates.append((-overlap, end - start, start, name, end))
        any_fit = False
        for _, _, start, name, end in sorted(candidates):
            if len(selected) >= 5:
                break
            content = "".join(info["lines"][start - 1:end])
            if append(chunk.path, start, end, content, info["hash"], name, rank, "retrieved_function"):
                any_fit = True
                dependencies.append((chunk.path, name, start, end, rank))
            elif any(r["path"] == chunk.path and r["start_line"] <= start and r["end_line"] >= end for r in selected):
                any_fit = True
        if not any_fit:
            append(chunk.path, chunk.start_line, chunk.end_line, chunk.content, chunk.content_hash,
                   None, rank, "raw_chunk_fallback")
    seed_count = len(selected)
    # One dependency hop, after all seeds. Only complete functions that fit remaining capacity.
    for path, name, start, end, rank in dependencies:
        for other, target in sorted(dependency_refs(parsed[path], start, end, name)):
            other = other or path
            if other not in parsed or target not in parsed[other]["symbols"]:
                continue
            begin, finish, node = parsed[other]["symbols"][target]
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or len(selected) >= 20:
                continue
            append(other, begin, finish, "".join(parsed[other]["lines"][begin - 1:finish]),
                   parsed[other]["hash"], target, rank, "static_function_dependency")
    return selected, {"seed_count": seed_count, "max_seeds": 5, "max_chars": limit,
                      "dependency_depth": 1, "evidence_chars": used, "rejected": rejected}
