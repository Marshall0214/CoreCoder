"""Bounded lexical evidence construction followed by one structured patch request."""

import ast
import hashlib
import json
from pathlib import Path

from corecoder.retrieval.keyword import KeywordIndex

from .fixed_evidence import generate_patch


def local_imports(name: str, text: str, allowed_files) -> list[str]:
    """Resolve static Python imports only; never import or execute repository code."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.replace(".", "/") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            parents = list(Path(name).parent.parts)
            if node.level > len(parents) + 1:
                continue
            prefix = parents[:len(parents) - node.level + 1] if node.level else []
            module = [part for part in (node.module or "").split(".") if part]
            base = "/".join(prefix + module)
            if base:
                modules.add(base)
            modules.update("/".join(prefix + module + [alias.name]) for alias in node.names if alias.name != "*")
    candidates = {path for module in modules for path in (module + ".py", module + "/__init__.py")}
    return sorted(candidates & set(allowed_files))


def bounded_evidence(workspace: Path, description: str, allowed_files, config, events):
    workspace = workspace.resolve()
    index = KeywordIndex(workspace, allowed_files)
    metadata = index.refresh()
    versions = {chunk.path: chunk.content_hash for chunk in index.chunks}
    query = description + " contract contracts"
    ranked = index.rank(query)
    seeds, seen = [], set()
    for score, chunk in ranked:
        if chunk.path not in seen:
            seeds.append({"path": chunk.path, "score": round(score, 6), "content_hash": chunk.content_hash})
            seen.add(chunk.path)
        if len(seeds) >= config.evidence_top_k:
            break
    queue = [(item["path"], 0, "keyword", item["content_hash"]) for item in seeds]
    files, selected, discarded, visited, chars = [], [], [], set(), 0
    for name, depth, reason, expected_hash in queue:
        if name in visited:
            continue
        visited.add(name)
        target = workspace / name
        if target.is_symlink() or not target.resolve().is_relative_to(workspace):
            raise ValueError("Evidence path changed to a link or escaped workspace")
        data = target.read_bytes()
        content_hash = hashlib.sha256(data).hexdigest()
        if expected_hash is not None and content_hash != expected_hash:
            raise ValueError("Indexed evidence changed before selection")
        text = data.decode("utf-8")
        if len(files) >= 20 or chars + len(text) > config.search_max_chars:
            discarded.append({"path": name, "reason": "full_file_budget", "chars": len(text)})
            continue
        files.append({"path": name, "content_hash": content_hash, "content": text})
        selected.append({"path": name, "depth": depth, "reason": reason, "chars": len(text)})
        chars += len(text)
        if name.endswith(".py") and depth < config.evidence_dependency_depth:
            for path in local_imports(name, text, allowed_files):
                if path in versions:
                    queue.append((path, depth + 1, "local_import", versions[path]))
                else:
                    discarded.append({"path": path, "reason": "not_indexed"})
    events.emit("pipeline_evidence_built", query=query, index=metadata, seeds=seeds,
                selected=selected, discarded=discarded, evidence_chars=chars,
                max_chars=config.search_max_chars, top_k=config.evidence_top_k,
                dependency_depth=config.evidence_dependency_depth)
    return files


def ordered_evidence(evidence, policy, events):
    """Reorder only after selection and budgeting; preserve every selected byte."""
    if policy not in {"selection", "path"}:
        raise ValueError("Unknown evidence order")
    ordered = sorted(evidence, key=lambda item: item["path"]) if policy == "path" else list(evidence)
    canonical = sorted(evidence, key=lambda item: item["path"])

    def digest(items):
        return hashlib.sha256(json.dumps(items, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()

    events.emit("pipeline_evidence_ordered", policy=policy,
                selection_paths=[item["path"] for item in evidence],
                request_paths=[item["path"] for item in ordered],
                evidence_set_hash=digest(canonical), ordered_evidence_hash=digest(ordered))
    return ordered


def run_pipeline(llm, workspace, description, allowed_files, config, events):
    evidence = bounded_evidence(workspace, description, allowed_files, config, events)
    evidence = ordered_evidence(evidence, config.evidence_order, events)
    return generate_patch(llm, workspace, description, allowed_files, events, evidence,
                          protocol="bounded-pipeline-v1", response_name="pipeline-response.txt")
