import hashlib
import json

import pytest

from corecoder.retrieval.keyword import Chunk
from docs.experiments import real_retrieval_audit_v1 as audit
from evals.runner import digest, snapshot


def test_full_chunk_probe_keeps_exact_ranges_and_never_truncates():
    large = Chunk("large.py", 1, 40, "x" * 6001, "hash-large")
    small = Chunk("small.py", 41, 42, "line one\nline two", "hash-small")
    result = audit.bounded_chunks([(2, large), (1, small)], top_k=1)
    assert result["selected"] == [{"path": "small.py", "start_line": 41, "end_line": 42,
                                    "content_hash": "hash-small", "content": small.content, "rank": 2, "score": 1}]
    assert result["discarded"][0]["reason"] == "full_chunk_budget"
    assert result["evidence_chars"] == len(small.content)


def test_span_recall_counts_union_not_duplicate_lines():
    spans = [{"path": "a.py", "start_line": 2, "end_line": 4}]
    selected = [{"path": "a.py", "start_line": 1, "end_line": 2}] * 2
    assert audit.span_recall(selected, spans) == pytest.approx(1 / 3)
    assert audit.span_recall([], spans) == 0
    with pytest.raises(ValueError, match="No upstream"):
        audit.span_recall([], [])


class Provider:
    model = "fake"
    model_digest = audit.EMBED_DIGEST
    dimension = 2

    def __init__(self):
        self.inputs = []
        self.usage = {"calls": 0, "inputs": 0}

    def embed(self, texts):
        self.inputs.extend(texts)
        self.usage["calls"] += 1
        self.usage["inputs"] += len(texts)
        return [(1.0, 0.0) for _ in texts]

    def verify_identity(self):
        pass


def case(tmp_path, name="toy"):
    workspace = tmp_path / name / "before"
    (workspace / "src" / "click").mkdir(parents=True)
    (workspace / "src" / "click" / "entry.py").write_text("value = 1\n", encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "secret.py").write_text("target_secret", encoding="utf-8")
    return {"task_id": name, "before": workspace, "before_hash": digest(snapshot(workspace)),
            "description": "value", "allowed_files": ["src/click/entry.py"]}


def test_all_observations_persist_before_scoring_and_hidden_source_not_embedded(tmp_path, monkeypatch):
    cases = [case(tmp_path, name) for name in ("one", "two")]
    provider = Provider()
    output = tmp_path / "output"

    def labels(_):
        observed = json.loads((output / "observations.json").read_text(encoding="utf-8"))
        assert len(observed) == 2
        assert all("scores" not in row and "targets" not in row for row in observed)
        assert all("target_secret" not in text and "after_secret" not in text for text in provider.inputs)
        return ["src/click/entry.py"], [{"path": "src/click/entry.py", "start_line": 1, "end_line": 1}]

    monkeypatch.setattr(audit, "labels", labels)
    result = audit.evaluate(cases, output, provider)
    assert result["repair_llm_calls"] == 0
    assert result["summary"]["dense"]["chunk_changed_line_recall"] == 1
    assert result["observations_sha256"] == hashlib.sha256((output / "observations.json").read_bytes()).hexdigest()


def test_output_inside_snapshot_and_wrong_embedding_identity_fail_before_calls(tmp_path):
    task = case(tmp_path)
    provider = Provider()
    with pytest.raises(ValueError, match="outside"):
        audit.evaluate([task], task["before"] / "output", provider)
    provider.model_digest = "wrong"
    with pytest.raises(ValueError, match="model differs"):
        audit.evaluate([task], tmp_path / "output", provider)
    assert not provider.inputs


def test_after_labels_use_before_line_anchors_and_validate_catalog(tmp_path):
    task = case(tmp_path)
    task["catalog"] = tmp_path / "catalog.json"
    task["admission_path"] = tmp_path / "admission.json"
    after = task["before"].parent / "after"
    (after / "src" / "click").mkdir(parents=True)
    (after / "src" / "click" / "entry.py").write_text("# inserted\nvalue = 1\n", encoding="utf-8")
    task["catalog"].write_text(json.dumps({"cases": [{"case_id": "toy", "changed_source_files": ["src/click/entry.py"]}]}), encoding="utf-8")
    task["admission_path"].write_text(json.dumps({"cases": [{"case_id": "toy", "revisions": {
        "after": {"tree_hash": digest(snapshot(after))}}}]}), encoding="utf-8")
    task["catalog_sha256"] = audit.sha(task["catalog"])
    task["admission_sha256"] = audit.sha(task["admission_path"])
    files, spans = audit.labels(task)
    assert files == ["src/click/entry.py"]
    assert spans == [{"path": "src/click/entry.py", "start_line": 1, "end_line": 1, "operation": "insert"}]
    task["catalog"].write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="provenance"):
        audit.labels(task)
