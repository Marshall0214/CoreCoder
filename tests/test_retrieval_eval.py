import json

import pytest

from evals import retrieval_eval
from evals.retrieval_eval import collect, coverage, evaluate, file_ranking, score
from evals.runner import DEFAULT_SUITE
from evals.schema import RunConfig, Task, load_suite


def config(**options):
    return RunConfig(mode="pipeline", search_backend="keyword", **options)


def test_file_rank_and_mrr_do_not_count_duplicate_chunks():
    class Chunk:
        def __init__(self, path):
            self.path = path

    ranking = file_ranking([(4, Chunk("docs.md")), (3, Chunk("docs.md")), (2, Chunk("fix.py"))])
    assert ranking == ["docs.md", "fix.py"]
    metrics = score({"ranking": ranking, "seeds": ranking[:1], "dependency_closure": ["fix.py"],
                     "selected": ["fix.py"]}, {"fix.py", "other.py"})
    assert metrics["reciprocal_rank"] == 0.5
    assert metrics["seed"]["recall"] == 0
    assert metrics["expanded"]["recall"] == metrics["selected"]["recall"] == 0.5
    assert metrics["selected"]["missing"] == ["other.py"]


def test_empty_ranking_is_a_miss_and_empty_labels_are_rejected():
    observation = {key: [] for key in ["ranking", "seeds", "dependency_closure", "selected"]}
    assert score(observation, {"fix.py"})["reciprocal_rank"] == 0
    with pytest.raises(ValueError, match="nonempty"):
        coverage([], [])


def test_unbounded_dependency_diagnostic_does_not_hide_budget_loss(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "entry.py").write_text("from leaf import value\n" + "# needle\n" * 60, encoding="utf-8")
    (workspace / "leaf.py").write_text("value = 1\n", encoding="utf-8")
    task = Task("toy", "toy", "needle", ("entry.py", "leaf.py"), tmp_path)
    observation = collect(task, config(evidence_top_k=1, search_max_chars=256), tmp_path / "trace.jsonl")
    metrics = score(observation, {"leaf.py"})
    assert metrics["expanded"]["recall"] == 1
    assert metrics["selected"]["recall"] == 0
    assert observation["selection"]["discarded"][0]["reason"] == "full_file_budget"


def test_labels_loaded_after_retrieval_and_cannot_change_evidence(tmp_path, monkeypatch):
    suite = DEFAULT_SUITE / "localization-v1"
    task = load_suite(suite, ["pagination-cursor"])[0]
    observations = []
    original = retrieval_eval.collect

    def tracking_collect(*args):
        observed = original(*args)
        observations.append(observed)
        return observed

    monkeypatch.setattr(retrieval_eval, "collect", tracking_collect)
    monkeypatch.setattr(retrieval_eval, "load_suite", lambda _: [task])

    def labels(_):
        assert len(observations) == 2
        return [{"file": "query.py"}]

    monkeypatch.setattr(retrieval_eval, "reference_edits", labels)
    first = evaluate([suite], [5, 10], tmp_path / "first", config())
    observations.clear()
    monkeypatch.setattr(retrieval_eval, "reference_edits", lambda _: [{"file": "feed.py"}])
    second = evaluate([suite], [5, 10], tmp_path / "second", config())
    for before, after in zip(first["rows"], second["rows"]):
        for key in ["query", "ranking", "seeds", "dependency_closure", "selected", "evidence_manifest"]:
            assert before["observation"][key] == after["observation"][key]
        assert before["metrics"] != after["metrics"]


def test_default_suites_are_scored_separately_and_reports_persist(tmp_path):
    report = evaluate([DEFAULT_SUITE, DEFAULT_SUITE / "localization-v1", DEFAULT_SUITE / "retrieval-overlap-v1"],
                      [5, 10], tmp_path / "reports", config())
    assert len(report["rows"]) == 22
    assert sorted(group["tasks"] for group in report["aggregates"]) == [1, 1, 5, 5, 5, 5]
    assert report["model_calls"] == 0
    saved = json.loads((tmp_path / "reports/report.json").read_text(encoding="utf-8"))
    assert saved["rows"] == report["rows"]
    assert all(0 <= group["mrr"] <= 1 for group in report["aggregates"])


@pytest.mark.parametrize("widths", [[], [5, 5], [0]])
def test_invalid_widths_fail_before_retrieval(tmp_path, widths):
    with pytest.raises(ValueError):
        evaluate([DEFAULT_SUITE], widths, tmp_path / "invalid", config())


def test_output_inside_fixtures_is_rejected(tmp_path):
    task = load_suite(DEFAULT_SUITE, ["timeout-units"])[0]
    with pytest.raises(ValueError, match="fixtures"):
        evaluate([DEFAULT_SUITE], [5], task.root / "workspace/offline-report", config())
