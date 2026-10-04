import json
import os

import pytest

from corecoder.demo import ScriptedLLM
from corecoder.llm import LLMResponse
from evals.fixed_evidence import apply_patch_json, diagnose, public_evidence
from evals.runner import DEFAULT_SUITE, reference_edits, run_task
from evals.runtime import Events
from evals.schema import RunConfig, load_suite


def sample(tmp_path):
    (tmp_path / "code.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/contract.md").write_text("x must be 3", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_secret.py").write_text("DO_NOT_SEND", encoding="utf-8")
    (tmp_path / "reference.json").write_text("ORACLE", encoding="utf-8")
    return public_evidence(tmp_path, ["code.py"])


def test_evidence_excludes_tests_and_reference_material(tmp_path):
    evidence = sample(tmp_path)
    assert {item["path"] for item in evidence} == {"code.py", "docs/contract.md"}
    assert "DO_NOT_SEND" not in json.dumps(evidence)
    assert "ORACLE" not in json.dumps(evidence)


@pytest.mark.parametrize("edit", [
    {"file": "../escape.py", "old": "x", "new": "z"},
    {"file": "tests/test_secret.py", "old": "DO_NOT_SEND", "new": ""},
    {"file": "code.py", "old": "missing", "new": "z"},
    {"file": "code.py", "old": "", "new": "z"},
    {"file": "code.py", "old": "x", "new": "z", "extra": True},
])
def test_invalid_later_edit_does_not_partially_apply(tmp_path, edit):
    evidence = sample(tmp_path)
    before = (tmp_path / "code.py").read_bytes()
    response = json.dumps({"edits": [{"file": "code.py", "old": "x = 1", "new": "x = 3"}, edit]})
    with pytest.raises(ValueError):
        apply_patch_json(response, tmp_path, ["code.py"], evidence)
    assert (tmp_path / "code.py").read_bytes() == before


def test_changed_version_rejects_patch(tmp_path):
    evidence = sample(tmp_path)
    (tmp_path / "code.py").write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        apply_patch_json('{"edits":[{"file":"code.py","old":"x = 2","new":"x = 3"}]}',
                         tmp_path, ["code.py"], evidence)


def test_writer_preserves_crlf_and_skips_unchanged_edits(tmp_path):
    (tmp_path / "code.py").write_bytes(b"x = 1\r\ny = 2\r\n")
    (tmp_path / "same.py").write_bytes(b"z = 0\r\n")
    allowed = ["code.py", "same.py"]
    evidence = public_evidence(tmp_path, allowed)
    response = json.dumps({"edits": [{"file": "code.py", "old": "x = 1", "new": "x = 3"},
                                     {"file": "same.py", "old": "z = 0", "new": "z = 0"}]})
    assert apply_patch_json(response, tmp_path, allowed, evidence) == ["code.py"]
    assert (tmp_path / "code.py").read_bytes() == b"x = 3\r\ny = 2\r\n"
    assert (tmp_path / "same.py").read_bytes() == b"z = 0\r\n"


def test_invalid_json_is_preserved_without_model_retry(tmp_path):
    sample(tmp_path)
    events = Events(tmp_path / "trace.jsonl", "test")
    llm = ScriptedLLM([LLMResponse(content="```json\n{}\n```")])
    result = diagnose(llm, tmp_path, "fix x", ["code.py"], events)
    assert result["status"] == "invalid_patch"
    assert (tmp_path / "diagnostic-response.txt").read_text(encoding="utf-8").startswith("```json")
    assert (tmp_path / "code.py").read_text(encoding="utf-8").startswith("x = 1")


@pytest.mark.parametrize("policy", [{"search_backend": "keyword"}, {"context_policy": "read-cover"},
                                   {"prompt_policy": "contract-check"}])
def test_agent_policy_cannot_silently_mix_with_diagnostic(policy):
    with pytest.raises(ValueError):
        RunConfig(mode="fixed-evidence", **policy)


def test_parent_verifies_mock_diagnostic_and_excludes_it_from_benchmark(tmp_path, monkeypatch):
    from evals import runner, worker

    task = load_suite(DEFAULT_SUITE / "localization-v1", ["pagination-cursor"])[0]
    edits = reference_edits(task)
    payload = json.dumps({"edits": edits})
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
    report = run_task(task, RunConfig(mode="fixed-evidence", base_url="http://localhost:11434/v1"), tmp_path)
    assert report["accepted"], report
    assert not report["benchmark_eligible"]
    assert report["metrics"]["llm_calls"] == 1
    assert report["tool_calls"] == 0
    job = json.loads((tmp_path / report["run_id"] / "job.json").read_text(encoding="utf-8"))
    assert "oracle_edits" not in job
    assert len(report["verification"]["changed_files"]) == 2
