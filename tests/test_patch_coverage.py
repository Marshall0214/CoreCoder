import hashlib
import json
import os

import pytest

from corecoder.demo import ScriptedLLM
from corecoder.llm import LLMResponse
from evals.fixed_evidence import SYSTEM, generate_patch, public_evidence
from evals.runner import DEFAULT_SUITE, run_task
from evals.runtime import Events
from evals.schema import RunConfig, load_suite


def sample(tmp_path):
    (tmp_path / "code.py").write_bytes(b"x = 1\r\n")
    (tmp_path / "contract.md").write_text("x must equal 3", encoding="utf-8")
    evidence = public_evidence(tmp_path, ["code.py"])
    evidence.append({"path": "contract.md", "content_hash": "unused", "content": "x must equal 3"})
    claim = {"behavior": "x equals 3", "evidence_file": "contract.md", "evidence_quote": "x must equal 3",
             "code_files": ["code.py"], "action": "edit"}
    payload = {"coverage": [claim], "edits": [{"file": "code.py", "old": "x = 1", "new": "x = 3"}]}
    return evidence, payload


def invoke(tmp_path, evidence, payload):
    llm = ScriptedLLM([LLMResponse(content=json.dumps(payload), prompt_tokens=50, completion_tokens=50)])
    return generate_patch(llm, tmp_path, "fix x", ["code.py"], Events(tmp_path / "trace.jsonl", "test"),
                          evidence, protocol="bounded-pipeline-v1", policy="contract-coverage")


def test_grounded_coverage_applies_patch_and_preserves_crlf(tmp_path):
    evidence, payload = sample(tmp_path)
    result = invoke(tmp_path, evidence, payload)
    assert result["status"] == "completed"
    assert result["coverage_claims"] == payload["coverage"]
    assert (tmp_path / "code.py").read_bytes() == b"x = 3\r\n"
    records = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    validation = next(row for row in records if row["event"] == "pipeline_coverage_validated")
    assert validation["semantic_coverage_verified"] is False


@pytest.mark.parametrize("change", [
    {"evidence_quote": "invented contract"}, {"evidence_file": "hidden_tests/test_target.py"},
    {"code_files": ["unprovided.py"]}, {"code_files": ["contract.md"]}, {"action": "verified"},
    {"extra": True}, {"behavior": " "},
])
def test_invalid_auxiliary_coverage_cannot_discard_a_valid_patch(tmp_path, change):
    evidence, payload = sample(tmp_path)
    payload["coverage"][0].update(change)
    result = invoke(tmp_path, evidence, payload)
    assert result["status"] == "completed"
    assert result["coverage_status"] == "invalid"
    assert "coverage_claims" not in result
    assert (tmp_path / "code.py").read_bytes() == b"x = 3\r\n"
    assert json.loads((tmp_path / "diagnostic-response.txt").read_text(encoding="utf-8")) == payload


def test_description_citations_and_false_claims_are_not_semantic_verification(tmp_path):
    evidence, payload = sample(tmp_path)
    payload["coverage"][0].update(evidence_file="description", evidence_quote="fix x", action="preserve")
    payload["edits"] = []
    result = invoke(tmp_path, evidence, payload)
    assert result["status"] == "completed"
    assert not result["edited_files"]
    assert (tmp_path / "code.py").read_bytes() == b"x = 1\r\n"


def test_empty_coverage_and_extra_top_level_fields_are_rejected(tmp_path):
    evidence, payload = sample(tmp_path)
    payload["coverage"] = []
    assert invoke(tmp_path, evidence, payload)["coverage_status"] == "invalid"
    payload["unexpected"] = True
    assert invoke(tmp_path, evidence, payload)["status"] == "invalid_patch"


def test_invalid_coverage_does_not_bypass_patch_validation(tmp_path):
    evidence, payload = sample(tmp_path)
    payload["coverage"][0]["evidence_quote"] = "fabricated"
    payload["edits"][0]["file"] = "../escape.py"
    result = invoke(tmp_path, evidence, payload)
    assert result["status"] == "invalid_patch"
    assert result["coverage_status"] == "invalid"
    assert (tmp_path / "code.py").read_bytes() == b"x = 1\r\n"


def test_baseline_prompt_and_payload_hash_are_unchanged(tmp_path):
    evidence, _ = sample(tmp_path)
    payload = json.dumps({"description": "fix x", "allowed_files": ["code.py"], "files": evidence}, ensure_ascii=False)
    llm = ScriptedLLM([LLMResponse(content='{"edits":[]}')])
    result = generate_patch(llm, tmp_path, "fix x", ["code.py"], Events(tmp_path / "trace.jsonl", "test"), evidence)
    assert result["prompt_hash"] == hashlib.sha256((SYSTEM + "\n" + payload).encode()).hexdigest()
    assert "coverage_claims" not in result


@pytest.mark.parametrize("options", [{"patch_policy": "unknown"}, {"mode": "live", "patch_policy": "contract-coverage"},
                                    {"mode": "fixed-evidence", "patch_policy": "contract-coverage"}])
def test_invalid_or_unused_patch_policy_is_rejected(options):
    with pytest.raises(ValueError):
        RunConfig(**options)


def test_worker_coverage_claim_cannot_override_independent_grading(tmp_path, monkeypatch):
    from evals import runner, worker

    task = load_suite(DEFAULT_SUITE / "localization-v1", ["pagination-cursor"])[0]
    payload = {"coverage": [{"behavior": "All repairs complete", "evidence_file": "description",
                             "evidence_quote": "browse_records", "code_files": ["query.py"], "action": "preserve"}],
               "edits": []}
    monkeypatch.setattr(worker, "TracedLLM", lambda *args, **kwargs: ScriptedLLM([
        LLMResponse(content=json.dumps(payload), prompt_tokens=100, completion_tokens=100)]))
    monkeypatch.setattr(worker, "ollama_metadata", lambda config: None)

    def run(args, cwd, timeout, stdout, stderr, env):
        previous = os.getcwd()
        try:
            assert worker.main(type(tmp_path)(args[-1])) == 0
        finally:
            os.chdir(previous)
        return {"seconds": 0, "timed_out": False, "returncode": 0}

    monkeypatch.setattr(runner, "run_process", run)
    report = run_task(task, RunConfig(mode="pipeline", search_backend="keyword", patch_policy="contract-coverage",
                                     base_url="http://localhost:11434/v1"), tmp_path)
    assert not report["accepted"]
    assert report["status"] == "failed_verification"
    assert report["worker"]["status"] == "completed"
    assert report["metrics"]["llm_calls"] == 1
