import json
import shutil

import pytest

from corecoder.llm import LLMResponse
from evals.contract_feedback import run_contract_feedback, validate_checks
from evals.runner import snapshot, verify
from evals.runtime import Events
from evals.schema import RunConfig, Task

CODE = "import unittest\nfrom value import value\nclass Public(unittest.TestCase):\n    def test_value(self):\n        self.assertEqual(value(), 3)\n"


class RecordingLLM:
    def __init__(self, answers):
        self.answers, self.messages = list(answers), []

    def chat(self, messages, tools):
        assert tools == []
        self.messages.append(messages)
        return LLMResponse(content=json.dumps(self.answers.pop(0)))


def setup_run(tmp_path, answers, source="def value():\n    return 1\n", public_check_policy="generated"):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "value.py").write_text(source, encoding="utf-8")
    (workspace / "docs").mkdir()
    (workspace / "docs" / "contract.md").write_text("value contract: value() must return 3", encoding="utf-8")
    llm = RecordingLLM(answers)
    result = run_contract_feedback(llm, workspace, "value() must return 3", ["value.py"],
                                   RunConfig(mode="contract-feedback", search_backend="keyword", public_check_policy=public_check_policy),
                                   Events(tmp_path / "trace.jsonl", "test"))
    return result, llm, workspace


def patch(old, new):
    return {"edits": [{"file": "value.py", "old": old, "new": new}]}


def test_frozen_checks_feedback_refresh_and_single_retry(tmp_path):
    result, llm, workspace = setup_run(tmp_path, [{"code": CODE}, patch("return 1", "return 2"),
                                                patch("return 2", "return 3")])
    checks = result["public_checks"]
    assert checks["original"]["assertion_failure"] and checks["candidate"]["assertion_failure"]
    assert checks["final"]["passed"] and result["feedback_attempts"] == 1
    assert len(llm.messages) == 3
    followup = json.loads(llm.messages[-1][1]["content"])
    assert followup["public_check_feedback"]["frozen_test_code"] == CODE
    assert "return 2" in next(f["content"] for f in followup["files"] if f["path"] == "value.py")
    assert (tmp_path / "public-contract-checks.py").read_text() == CODE
    assert sorted(p.name for p in workspace.iterdir()) == ["docs", "value.py"]
    assert "return 3" in (workspace / "value.py").read_text()


def test_failed_retry_stops_with_completed_patch_not_false_success(tmp_path):
    result, llm, _ = setup_run(tmp_path, [{"code": CODE}, patch("return 1", "return 2"), {"edits": []}])
    assert len(llm.messages) == 3 and result["status"] == "completed"
    assert not result["public_checks"]["final"]["passed"]
    # completed means patch execution completed; only parent grader assigns accepted.
    assert "accepted" not in result


def test_correct_initial_patch_does_not_request_feedback(tmp_path):
    result, llm, _ = setup_run(tmp_path, [{"code": CODE}, patch("return 1", "return 3")])
    assert len(llm.messages) == 2 and result["feedback_attempts"] == 0
    assert result["public_checks"]["candidate"]["passed"]


def test_non_discriminating_checks_do_not_trigger_retry(tmp_path):
    result, llm, _ = setup_run(tmp_path, [{"code": CODE.replace("value(), 3", "value(), 1")},
                                        patch("return 1", "return 2")])
    assert result["public_checks"]["original"]["passed"]
    assert len(llm.messages) == 2


def test_import_error_is_not_behavior_feedback(tmp_path):
    result, llm, _ = setup_run(tmp_path, [{"code": CODE.replace("from value import value", "from value import missing as value")},
                                        {"edits": []}])
    assert not result["public_checks"]["original"]["assertion_failure"]
    assert len(llm.messages) == 2


@pytest.mark.parametrize("code", ["import os\n" + CODE, CODE + "open('secret')\n", "bad python !",
                                   "import unittest\n", CODE + "value.__globals__\n"])
def test_invalid_generation_still_runs_initial_patch(tmp_path, code):
    result, llm, _ = setup_run(tmp_path, [{"code": code}, patch("return 1", "return 3")])
    assert result["public_checks"]["generation_status"] == "invalid"
    assert result["status"] == "completed" and len(llm.messages) == 2


def test_payload_and_shape_validation():
    with pytest.raises(ValueError):
        validate_checks(json.dumps({"code": CODE, "extra": 1}), ["value.py"])
    with pytest.raises(ValueError):
        RunConfig(mode="contract-feedback")


def test_zero_discovered_tests_cannot_trigger_feedback(tmp_path):
    code = "import unittest\nclass Plain:\n    def test_value(self):\n        self.assertEqual(1, 3)\n"
    result, llm, _ = setup_run(tmp_path, [{"code": code}, {"edits": []}])
    assert result["public_checks"]["original"]["tests_run"] == 0
    assert not result["public_checks"]["candidate"]["passed"] and len(llm.messages) == 2


def test_wrong_public_checks_cannot_replace_independent_grader(tmp_path):
    result, llm, workspace = setup_run(tmp_path, [{"code": CODE.replace("value(), 3", "value(), 1")}, {"edits": []}])
    assert result["public_checks"]["candidate"]["passed"]
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    shutil.copytree(workspace, fixture / "workspace")
    visible = fixture / "workspace" / "tests"
    visible.mkdir()
    (visible / "test_visible.py").write_text(CODE.replace("value(), 3", "value(), 1"), encoding="utf-8")
    hidden = fixture / "hidden_tests"
    hidden.mkdir()
    (hidden / "test_target.py").write_text(CODE, encoding="utf-8")
    task = Task("sample", "sample", "value() must return 3", ("value.py",), fixture)
    outcome = verify(task, workspace, tmp_path, snapshot(workspace), 15)
    assert not outcome["passed"] and not outcome["target"]["passed"]
    assert all("test_target" not in json.dumps(messages) for messages in llm.messages)
