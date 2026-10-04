import json
import os

import pytest

from corecoder.demo import ScriptedLLM
from corecoder.llm import LLMResponse
from evals.fixed_evidence import apply_patch_json
from evals.pipeline import bounded_evidence, local_imports
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


@pytest.mark.parametrize("options", [{"search_backend": "off"}, {"search_backend": "keyword", "evidence_top_k": 0},
                                    {"search_backend": "keyword", "evidence_dependency_depth": 4},
                                    {"search_backend": "keyword", "prompt_policy": "contract-check"}])
def test_pipeline_config_cannot_silently_change_protocol(options):
    with pytest.raises(ValueError):
        RunConfig(mode="pipeline", **options)


def test_worker_and_parent_use_pipeline_evidence_and_original_grader(tmp_path, monkeypatch):
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
                                     base_url="http://localhost:11434/v1"), tmp_path)
    assert report["accepted"], report
    assert report["evaluation_protocol"] == "bounded-pipeline-v1"
    assert report["metrics"]["llm_calls"] == 1
    assert report["benchmark_eligible"]
    job = json.loads((tmp_path / report["run_id"] / "job.json").read_text(encoding="utf-8"))
    assert "oracle_edits" not in job
    mixed = [report, {**report, "evaluation_protocol": "agent-loop-v1"}]
    summary_path = write_summary(mixed, tmp_path).with_suffix(".json")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert not summary["benchmark_eligible"]
