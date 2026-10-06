import hashlib

import pytest

from corecoder.retrieval.keyword import KeywordIndex
from docs.experiments.dependency_context_v1 import expand
from docs.experiments.dependency_repair_v1 import POLICIES, analyze


def seed(workspace, name="entry.py", budget=6000, allowed=None):
    index = KeywordIndex(workspace, allowed)
    metadata = index.refresh()
    raw = (workspace / name).read_bytes()
    rows = [{"path": name, "content": raw.decode("utf-8"), "content_hash": hashlib.sha256(raw).hexdigest()}]
    return rows, {"index_hash": metadata["index_hash"], "max_chars": budget,
                  "selected_paths": [name], "discarded": [], "top_k": 5}


def test_depth_two_closure_preserves_seeds_and_never_executes_source(tmp_path):
    (tmp_path / "entry.py").write_text("from helper import work\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text("from leaf import value\nraise RuntimeError('never execute')\n", encoding="utf-8")
    (tmp_path / "leaf.py").write_bytes(b"from beyond import value\r\n")
    (tmp_path / "beyond.py").write_text("value = 42\n", encoding="utf-8")
    seeds, metadata = seed(tmp_path)
    evidence, audit = expand(tmp_path, ["entry.py", "helper.py", "leaf.py", "beyond.py"], seeds, metadata)
    assert evidence[:1] == seeds
    assert [e["path"] for e in evidence] == ["entry.py", "helper.py", "leaf.py"]
    assert evidence[-1]["content"] == "from beyond import value\r\n"
    assert [e["depth"] for e in audit["added"]] == [1, 2]
    assert audit["evidence_chars"] == sum(len(e["content"]) for e in evidence)


def test_budget_never_truncates_or_replaces_seed(tmp_path):
    (tmp_path / "entry.py").write_text("import huge\n", encoding="utf-8")
    (tmp_path / "huge.py").write_text("payload = '" + "x" * 100 + "'\n", encoding="utf-8")
    seeds, metadata = seed(tmp_path, budget=30)
    evidence, audit = expand(tmp_path, ["entry.py", "huge.py"], seeds, metadata)
    assert evidence == seeds
    assert audit["unshown_imports"] == ["huge.py"]
    assert audit["discarded"][-1]["reason"] == "dependency_budget"


def test_cycle_and_allowlist_do_not_leak_hidden_modules(tmp_path):
    (tmp_path / "entry.py").write_text("import helper\nimport secret\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text("import entry\n", encoding="utf-8")
    (tmp_path / "secret.py").write_text("hidden_answer = 1\n", encoding="utf-8")
    allowed = ["entry.py", "helper.py"]
    seeds, metadata = seed(tmp_path, allowed=allowed)
    evidence, audit = expand(tmp_path, allowed, seeds, metadata)
    assert [e["path"] for e in evidence] == ["entry.py", "helper.py"]
    assert all("hidden_answer" not in e["content"] for e in evidence)
    assert len(audit["added"]) == 1


def test_relative_imports_are_resolved_without_package_execution(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "entry.py").write_text("from .helper import work\n", encoding="utf-8")
    (tmp_path / "pkg" / "helper.py").write_text("work = 1\n", encoding="utf-8")
    allowed = ["pkg/entry.py", "pkg/helper.py"]
    seeds, metadata = seed(tmp_path, "pkg/entry.py", allowed=allowed)
    evidence, _ = expand(tmp_path, allowed, seeds, metadata)
    assert evidence[-1]["path"] == "pkg/helper.py"


def test_changed_and_forged_seed_evidence_fail(tmp_path):
    (tmp_path / "entry.py").write_text("x = 1\n", encoding="utf-8")
    seeds, metadata = seed(tmp_path)
    seeds[0]["content"] = "x = 2\n"
    with pytest.raises(ValueError, match="differs"):
        expand(tmp_path, ["entry.py"], seeds, metadata)
    (tmp_path / "entry.py").write_text("x = 3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="corpus"):
        expand(tmp_path, ["entry.py"], seeds, metadata)


def test_factorial_analysis_requires_all_fresh_branches_and_tracks_regressions():
    tasks = [f"task-{i}" for i in range(11)]
    runs = []
    for task in tasks:
        for policy in POLICIES:
            accepted = task == "task-0" and policy in {"bm25-seeds", "dense-imports"}
            runs.append({"task_id": task, "strategy": policy, "accepted": accepted,
                         "status": "passed" if accepted else "failed_verification",
                         "packing": {"selected_paths": []},
                         "worker": {"metrics": {"missing_usage_calls": 0, "budget_accounted_tokens": 10}}})
    report = {"complete": True, "protocol": {"task_hashes": dict.fromkeys(tasks)}, "runs": runs}
    matrix = analyze(report)
    assert matrix["dependency_paired_effects"]["bm25"]["seeds_only"] == 1
    assert matrix["dependency_paired_effects"]["dense"]["imports_only"] == 1
    assert matrix["summary"]["dense-imports"]["repair_tokens"] == 110
    runs[-1] = runs[0]
    with pytest.raises(ValueError, match="44-run"):
        analyze(report)
