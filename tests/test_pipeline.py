import json
import os

import pytest

from corecoder.demo import ScriptedLLM
from corecoder.llm import LLMResponse
from evals.fixed_evidence import apply_patch_json
from evals.pipeline import bounded_evidence, local_imports, ordered_evidence
from evals.runner import DEFAULT_SUITE, reference_edits, run_task, write_summary
from evals.runtime import Events
from evals.schema import RunConfig, load_suite


def fixture(tmp_path):
    sources = {"entry.py": "from middle import run\n# needle\n", "middle.py": "from leaf import value\n",
               "leaf.py": "from entry import run\nvalue = 1\n", "distractor.py": "unused = 2\n"}
    for name, content in sources.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return list(sources), Events(tmp_path / "trace.jsonl", "test")


def test_import_expansion_is_bounded_and_cycles_do_not_duplicate(tmp_path):
    allowed, events = fixture(tmp_path)
    for depth, expected in ((0, {"entry.py"}), (1, {"entry.py", "middle.py"}),
                            (2, {"entry.py", "middle.py", "leaf.py"})):
        config = RunConfig(mode="pipeline", search_backend="keyword", evidence_top_k=1,
                           evidence_dependency_depth=depth)
        files = bounded_evidence(tmp_path, "needle", allowed, config, events)
        assert {item["path"] for item in files} == expected
        assert len(files) == len(expected)


def test_full_file_budget_drops_instead_of_truncating(tmp_path):
    allowed, events = fixture(tmp_path)
    (tmp_path / "entry.py").write_text("# needle\n" * 100, encoding="utf-8")
    config = RunConfig(mode="pipeline", search_backend="keyword", evidence_top_k=1, search_max_chars=256)
    assert bounded_evidence(tmp_path, "needle", allowed, config, events) == []
    last = json.loads(events.path.read_text(encoding="utf-8").splitlines()[-1])
    assert last["discarded"][0]["reason"] == "full_file_budget"
    assert last["evidence_chars"] == 0


def test_tests_and_labels_do_not_enter_evidence(tmp_path):
    allowed, events = fixture(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/secret.md").write_text("needle SECRET", encoding="utf-8")
    (tmp_path / "evaluation.json").write_text("needle ORACLE", encoding="utf-8")
    files = bounded_evidence(tmp_path, "needle", allowed,
                             RunConfig(mode="pipeline", search_backend="keyword"), events)
    assert "SECRET" not in json.dumps(files)
    assert "ORACLE" not in json.dumps(files)


def test_unsupplied_allowed_file_cannot_be_edited(tmp_path):
    allowed, events = fixture(tmp_path)
    files = bounded_evidence(tmp_path, "needle", allowed,
                             RunConfig(mode="pipeline", search_backend="keyword", evidence_top_k=1,
                                       evidence_dependency_depth=0), events)
    with pytest.raises(ValueError, match="not supplied"):
        apply_patch_json('{"edits":[{"file":"leaf.py","old":"value = 1","new":"value = 2"}]}',
                         tmp_path, allowed, files)


def test_relative_imports_are_static_and_external_imports_are_ignored():
    assert local_imports("pkg/entry.py", "from .middle import run\nimport os\n",
                         ["pkg/middle.py", "pkg/entry.py"]) == ["pkg/middle.py"]


@pytest.mark.parametrize("suite,task_id,changed", [("localization-v1", "pagination-cursor", False),
                                                 ("retrieval-overlap-v1", "lease-lifecycle", True)])
def test_width_intervention_is_checked_before_model_calls(tmp_path, suite, task_id, changed):
    task = load_suite(DEFAULT_SUITE / suite, [task_id])[0]
    evidence = []
    events = Events(tmp_path / "trace.jsonl", "width-test")
    for top_k in (5, 10):
        config = RunConfig(mode="pipeline", search_backend="keyword", evidence_top_k=top_k,
                           evidence_order="path")
        files = bounded_evidence(task.root / "workspace", task.description, task.allowed_files, config, events)
        evidence.append({item["path"]: item for item in files})
        assert sum(len(item["content"]) for item in files) <= config.search_max_chars
    assert (evidence[0] != evidence[1]) == changed
    assert evidence[0].keys() <= evidence[1].keys()
    assert all(item == evidence[1][path] for path, item in evidence[0].items())
    records = [json.loads(line) for line in events.path.read_text(encoding="utf-8").splitlines()]
    for record, top_k in zip(records, (5, 10)):
        assert record["seed_count"] == min(record["candidate_files"], top_k)
        assert record["ranked_chunks"] >= record["candidate_files"]


def test_order_changes_only_packing_and_preserves_selection_under_budget(tmp_path):
    allowed, events = fixture(tmp_path)
    config = RunConfig(mode="pipeline", search_backend="keyword", evidence_top_k=1)
    evidence = bounded_evidence(tmp_path, "needle", allowed, config, events)
    original = json.dumps(evidence)
    selection = ordered_evidence(evidence, "selection", events)
    paths = ordered_evidence(evidence, "path", events)
    assert json.dumps(evidence) == original
    assert selection == evidence
    assert paths == sorted(evidence, key=lambda item: item["path"])
    assert selection != paths
    records = [json.loads(line) for line in events.path.read_text(encoding="utf-8").splitlines()]
    assert records[-2]["evidence_set_hash"] == records[-1]["evidence_set_hash"]
    assert records[-2]["ordered_evidence_hash"] != records[-1]["ordered_evidence_hash"]


@pytest.mark.parametrize("options", [{"evidence_order": "unknown"}, {"mode": "live", "evidence_order": "path"}])
def test_invalid_or_unused_order_is_rejected(options):
    with pytest.raises(ValueError):
        RunConfig(**options)


@pytest.mark.parametrize("options", [{"search_backend": "off"}, {"search_backend": "keyword", "evidence_top_k": 0},
                                    {"search_backend": "keyword", "evidence_dependency_depth": 4},
                                    {"search_backend": "keyword", "prompt_policy": "contract-check"}])
def test_pipeline_config_cannot_silently_change_protocol(options):
    with pytest.raises(ValueError):
        RunConfig(mode="pipeline", **options)


@pytest.mark.parametrize("order", ["selection", "path"])
def test_worker_and_parent_use_pipeline_evidence_and_original_grader(tmp_path, monkeypatch, order):
    from evals import runner, worker

    task = load_suite(DEFAULT_SUITE / "localization-v1", ["pagination-cursor"])[0]
    payload = json.dumps({"edits": reference_edits(task)})
    monkeypatch.setattr(worker, "TracedLLM", lambda *args, **kwargs: ScriptedLLM([
        LLMResponse(content=payload, prompt_tokens=100, completion_tokens=100)]))
    monkeypatch.setattr(worker, "ollama_metadata", lambda config: None)

    def invoke(args, cwd, timeout, stdout, stderr, env):
        previous = os.getcwd()
        try:
            assert worker.main(type(tmp_path)(args[-1])) == 0
        finally:
            os.chdir(previous)
        return {"seconds": 0, "timed_out": False, "returncode": 0}

    monkeypatch.setattr(runner, "run_process", invoke)
    report = run_task(task, RunConfig(mode="pipeline", search_backend="keyword",
                                     base_url="http://localhost:11434/v1", evidence_order=order), tmp_path)
    assert report["accepted"], report
    assert report["evaluation_protocol"] == "bounded-pipeline-v1"
    assert report["metrics"]["llm_calls"] == 1
    assert report["benchmark_eligible"]
    paths = [item["path"] for item in report["worker"]["evidence_manifest"]]
    if order == "path":
        assert paths == sorted(paths)
    records = [json.loads(line) for line in (tmp_path / report["run_id"] / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    ordering = next(item for item in records if item["event"] == "pipeline_evidence_ordered")
    assert ordering["policy"] == order
    assert ordering["request_paths"] == paths
    job = json.loads((tmp_path / report["run_id"] / "job.json").read_text(encoding="utf-8"))
    assert "oracle_edits" not in job
    mixed = [report, {**report, "evaluation_protocol": "agent-loop-v1"}]
    summary_path = write_summary(mixed, tmp_path).with_suffix(".json")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert not summary["benchmark_eligible"]
