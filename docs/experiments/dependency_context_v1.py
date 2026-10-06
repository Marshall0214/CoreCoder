"""Public static import closure appended to frozen seed evidence within its budget."""

import hashlib

from corecoder.retrieval.keyword import KeywordIndex
from evals.pipeline import local_imports


def expand(workspace, allowed_files, seeds, metadata, max_depth=2):
    if max_depth != 2:
        raise ValueError("This protocol fixes dependency depth at two")
    index = KeywordIndex(workspace, allowed_files)
    if index.refresh()["index_hash"] != metadata["index_hash"]:
        raise ValueError("Public dependency corpus changed")
    versions = {chunk.path: chunk.content_hash for chunk in index.chunks}
    selected = [dict(item) for item in seeds]
    chars = sum(len(item["content"]) for item in selected)
    if chars > metadata["max_chars"]:
        raise ValueError("Seed evidence exceeds budget")
    names = [item["path"] for item in selected]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate seed evidence")
    for item in selected:
        path = workspace / item["path"]
        if item["path"] not in versions or path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("Seed evidence is outside the indexed public corpus")
        raw = path.read_bytes()
        if (versions[item["path"]] != item["content_hash"] or hashlib.sha256(raw).hexdigest() != item["content_hash"]
                or raw.decode("utf-8") != item["content"]):
            raise ValueError("Seed evidence differs from current source")
    queue = [(item, 0) for item in selected]
    visited, added, discarded, links = set(names), [], [], []
    for item, depth in queue:
        if not item["path"].endswith(".py") or depth >= max_depth:
            continue
        for name in local_imports(item["path"], item["content"], allowed_files):
            links.append({"from": item["path"], "to": name, "depth": depth + 1})
            if name in visited:
                continue
            visited.add(name)
            if name not in versions:
                discarded.append({"path": name, "reason": "not_indexed"})
                continue
            path = workspace / name
            if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
                raise ValueError("Dependency path escaped workspace")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != versions[name]:
                raise ValueError("Dependency source changed during capture")
            text = raw.decode("utf-8")
            if len(selected) >= 20 or chars + len(text) > metadata["max_chars"]:
                discarded.append({"path": name, "reason": "dependency_budget", "chars": len(text)})
                continue
            row = {"path": name, "content_hash": versions[name], "content": text}
            selected.append(row)
            queue.append((row, depth + 1))
            added.append({"path": name, "depth": depth + 1, "via": item["path"], "chars": len(text)})
            chars += len(text)
    result = {**metadata, "policy": "public-import-depth2", "dependency_depth": max_depth,
              "seed_paths": names, "selected_paths": [item["path"] for item in selected],
              "evidence_chars": chars, "added": added, "import_links": links,
              "discarded": metadata["discarded"] + discarded}
    result["unshown_imports"] = sorted({link["to"] for link in links} - set(result["selected_paths"]))
    return selected, result
