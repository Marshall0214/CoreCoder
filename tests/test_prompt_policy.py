import json

import pytest

from evals.prompts import CONTRACT_CHECK, repair_prompt
from evals.runner import DEFAULT_SUITE, run_task
from evals.runtime import VISIBLE_COMMAND
from evals.schema import RunConfig, load_suite


@pytest.mark.parametrize("backend", ["off", "none", "keyword"])
def test_baseline_prompt_preserves_existing_protocol(backend):
    expected = ("symptom\n\nAllowed source files: a.py. Read related modules before editing. "
                "Do not modify tests or create files. "
                f"The only permitted shell command is: {VISIBLE_COMMAND}. "
                "Fix the implementation; passing visible tests alone is not final acceptance.")
    if backend != "off":
        expected += (" Use search_code first to locate relevant code and documented contracts. "
                     "Check cross-module behavior and use read_file for full context before editing. "
                     "Search may return no evidence; existing read/glob/grep remain available.")
    assert repair_prompt("symptom", ["a.py"], backend) == expected
    assert repair_prompt("symptom", ["a.py"], backend, "contract-check") == expected + CONTRACT_CHECK


def test_invalid_prompt_policy_is_rejected():
    with pytest.raises(ValueError):
        RunConfig(prompt_policy="unknown")


def test_worker_policy_changes_prompt_but_not_tools_or_grading(tmp_path):
    task = load_suite(DEFAULT_SUITE / "localization-v1", ["pagination-cursor"])[0]
    reports = [run_task(task, RunConfig(mode="scripted", search_backend="keyword", prompt_policy=policy), tmp_path)
               for policy in ("baseline", "contract-check")]
    assert all(report["accepted"] for report in reports)
    for key in ("fixture_hash", "grader_hash", "manifest_hash"):
        assert reports[0][key] == reports[1][key]
    assert reports[0]["worker"]["tool_schema_hash"] == reports[1]["worker"]["tool_schema_hash"]
    assert reports[0]["worker"]["protocol_prompt_hash"] != reports[1]["worker"]["protocol_prompt_hash"]
    job = json.loads((tmp_path / reports[1]["run_id"] / "job.json").read_text(encoding="utf-8"))
    # Oracle-assisted scripted admission is explicit. Prompt builder receives only the three visible inputs.
    prompt = repair_prompt(job["description"], job["allowed_files"], "keyword", "contract-check")
    assert "old_string" not in prompt
    assert "hidden_tests" not in prompt
    assert "reference.json" not in prompt
