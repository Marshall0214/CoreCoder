import copy

import pytest

from corecoder.retrieval.keyword import KeywordIndex
from docs.experiments.vector_repair_v1 import STRATEGIES, config, pack, prepare


def observation(workspace):
    index = KeywordIndex(workspace)
    metadata = index.refresh()
    rows = [{"path": c.path, "start_line": c.start_line, "end_line": c.end_line,
             "content_hash": c.content_hash, "score": 1} for c in index.chunks]
    files = list(dict.fromkeys(c.path for c in index.chunks))
    return {"index": metadata, "rankings": {s: files[:] for s in STRATEGIES},
            "chunk_rankings": {s: copy.deepcopy(rows) for s in STRATEGIES}}


def test_pack_preserves_full_source_and_budget(tmp_path):
    (tmp_path / "a.py").write_bytes(b"alpha = 1\r\n")
    (tmp_path / "b.py").write_text("beta = 2\n", encoding="utf-8")
    observed = observation(tmp_path)
    evidence, metadata = pack(tmp_path, ["a.py", "b.py"], observed, "dense", max_chars=12)
    assert evidence[0]["content"] == "alpha = 1\r\n"
    assert metadata["evidence_chars"] == 11
    assert metadata["discarded"][0]["path"] == "b.py"
    assert metadata["selected_paths"] == ["a.py"]


def test_changed_corpus_and_invented_citation_fail(tmp_path):
    source = tmp_path / "a.py"
    source.write_text("alpha = 1\n", encoding="utf-8")
    observed = observation(tmp_path)
    bad = copy.deepcopy(observed)
    bad["chunk_rankings"]["dense"][0]["path"] = "../secret.py"
    with pytest.raises(ValueError, match="citation"):
        pack(tmp_path, ["a.py"], bad, "dense")
    source.write_text("alpha = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="corpus"):
        pack(tmp_path, ["a.py"], observed, "dense")


def test_missing_dense_chunks_and_mismatched_file_ranking_fail(tmp_path):
    (tmp_path / "a.py").write_text("alpha = 1\n", encoding="utf-8")
    observed = observation(tmp_path)
    observed["rankings"]["dense"] = []
    with pytest.raises(ValueError, match="File ranking"):
        pack(tmp_path, ["a.py"], observed, "dense")
    observed["chunk_rankings"]["dense"] = []
    with pytest.raises(ValueError, match="every indexed"):
        pack(tmp_path, ["a.py"], observed, "dense")


def test_production_config_is_fixed():
    current = config()
    assert current.model == "qwen3.5:27b"
    assert current.evidence_dependency_depth == 0
    assert current.search_max_chars == 6000
    assert current.token_budget == 15000
    assert current.max_output_tokens == 2048


def test_prepare_rejects_labels_before_starting_models(tmp_path):
    import json

    from evals.runner import DEFAULT_SUITE
    from evals.schema import load_suite

    tasks = [t for suite in (DEFAULT_SUITE, DEFAULT_SUITE / "localization-v1",
                            DEFAULT_SUITE / "retrieval-overlap-v1") for t in load_suite(suite)]
    rows = [{"task_id": t.task_id} for t in tasks]
    rows[0]["targets"] = ["secret.py"]
    path = tmp_path / "observations.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    with pytest.raises(ValueError, match="label-free"):
        prepare(path, tmp_path / "out")


def test_analysis_rejects_incomplete_runs_before_loading_labels(tmp_path, monkeypatch):
    import json

    from docs.experiments import vector_repair_analysis_v1 as analysis

    (tmp_path / "experiment.json").write_text(json.dumps({"complete": False, "runs": []}), encoding="utf-8")
    monkeypatch.setattr(analysis, "reference_edits", lambda _: pytest.fail("Labels read for incomplete batch"))
    with pytest.raises(ValueError, match="complete"):
        analysis.analyze(tmp_path)
