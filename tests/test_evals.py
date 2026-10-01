"""Acceptance boundaries for the trusted-fixture repair harness."""

import json
import shutil
import sys

import pytest

from corecoder.demo import ScriptedLLM
from corecoder.llm import LLMResponse, ToolCall
from evals.process import run_process, run_tests
from evals.process import test_environment as candidate_environment
from evals.runner import DEFAULT_SUITE, reference_edits, run_task, snapshot, verify
from evals.runtime import VISIBLE_COMMAND, BudgetExceeded, BudgetLLM, Events, make_tools
from evals.schema import RunConfig, load_suite, relative_path
from evals.worker import FixtureAgent

TASKS = load_suite(DEFAULT_SUITE)


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.task_id)
def test_bug_fails_and_reference_and_scripted_repairs_pass(task, tmp_path):
    broken = run_task(task, RunConfig(), tmp_path)
    assert broken["status"] == "failed_verification"
    assert not broken["verification"]["target"]["passed"]
    assert broken["verification"]["regression"]["passed"]
    for mode in ("reference", "scripted"):
        repaired = run_task(task, RunConfig(mode=mode), tmp_path)
        assert repaired["accepted"], repaired
        assert not repaired["benchmark_eligible"]
        assert repaired["fixture_hash"] == broken["fixture_hash"]
        assert repaired["artifacts"] != broken["artifacts"]
        events = [json.loads(line) for line in (tmp_path / repaired["run_id"] / "trace.jsonl").read_text().splitlines()]
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))


def candidate(task, tmp_path):
    workspace = tmp_path / "workspace"
    shutil.copytree(task.root / "workspace", workspace)
    return workspace, snapshot(workspace)


def test_modified_visible_tests_are_rejected_even_with_correct_patch(tmp_path):
    task = TASKS[0]
    workspace, before = candidate(task, tmp_path)
    for edit in reference_edits(task):
        path = workspace / edit["file"]
        path.write_text(path.read_text().replace(edit["old"], edit["new"]))
    (workspace / "tests/test_visible.py").write_text("# bypassed\n")
    result = verify(task, workspace, tmp_path, before, 5)
    assert not result["passed"]
    assert result["scope_violations"] == ["tests/test_visible.py"]
    assert result["target"] is None


def test_regression_failure_rejects_target_passing_patch(tmp_path):
    task = next(task for task in TASKS if task.task_id == "falsey-overrides")
    workspace, before = candidate(task, tmp_path)
    for edit in reference_edits(task):
        path = workspace / edit["file"]
        path.write_text(path.read_text().replace(edit["old"], edit["new"]))
    # Target checks zero/false/empty/None; visible tests also cover positive values.
    path = workspace / "options.py"
    path.write_text(path.read_text().replace("value is not None", "value is not None and value != 8"))
    result = verify(task, workspace, tmp_path, before, 5)
    assert result["target"]["passed"]
    assert not result["regression"]["passed"]
    assert not result["passed"]


@pytest.mark.parametrize("path", ["../escape.py", "/escape.py", "C:/escape.py", "x\\escape.py", "./x.py", "x//y.py"])
def test_task_paths_reject_escapes(path):
    with pytest.raises(ValueError):
        relative_path(path)


def test_tools_reject_escaping_reads_test_writes_and_arbitrary_commands(tmp_path):
    task = TASKS[0]
    workspace, before = candidate(task, tmp_path)
    tools = {tool.name: tool for tool in make_tools(workspace, list(task.allowed_files), Events(tmp_path / "trace", "test"), 5)}
    assert "escapes" in tools["read_file"].execute(file_path="../secret.txt")
    assert "Only allowed" in tools["write_file"].execute(file_path="tests/test_visible.py", content="pass")
    assert "Only the declared" in tools["bash"].execute(command="python -c 'print(1)'")
    assert snapshot(workspace) == before
    assert "exit code: 0" in tools["bash"].execute(command=VISIBLE_COMMAND)


def test_zero_discovered_tests_never_pass(tmp_path):
    (tmp_path / "empty").mkdir()
    result = run_tests(tmp_path, "empty", 5, tmp_path, "zero")
    assert result["returncode"] == 0
    assert result["tests_run"] == 0
    assert not result["passed"]


def test_timeout_stops_child_process(tmp_path):
    marker = tmp_path / "should-not-exist"
    child = f"import time; from pathlib import Path; time.sleep(3); Path({str(marker)!r}).write_text('leaked')"
    parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); time.sleep(20)"
    result = run_process([sys.executable, "-c", parent, child], tmp_path, 1,
                         tmp_path / "out", tmp_path / "err")
    assert result["timed_out"]
    # Give a leaked child enough time to leave its marker.
    run_process([sys.executable, "-c", "import time; time.sleep(3)"], tmp_path, 5,
                tmp_path / "wait-out", tmp_path / "wait-err")
    assert not marker.exists()


def test_missing_usage_is_unknown_and_preflight_blocks_calls(tmp_path):
    events = Events(tmp_path / "trace", "test")
    llm = BudgetLLM(ScriptedLLM([LLMResponse(content="done")]), RunConfig(), events)
    llm.chat([{"role": "user", "content": "hi"}])
    assert llm.metrics()["prompt_tokens"] is None
    assert llm.metrics()["missing_usage_calls"] == 1
    assert llm.metrics()["budget_accounted_tokens"] > 0
    blocked = BudgetLLM(ScriptedLLM([]), RunConfig(token_budget=1), events)
    with pytest.raises(BudgetExceeded):
        blocked.chat([{"role": "user", "content": "hi"}])
    assert blocked.calls == 0


def test_actual_usage_exceeding_budget_cannot_execute_tools(tmp_path, monkeypatch):
    task = TASKS[0]
    workspace, before = candidate(task, tmp_path)
    monkeypatch.chdir(workspace)
    events = Events(tmp_path / "trace", "test")
    llm = BudgetLLM(ScriptedLLM([LLMResponse(
        tool_calls=[ToolCall("x", "write_file", {"file_path": task.allowed_files[0], "content": "bad"})],
        prompt_tokens=50000, completion_tokens=10)]), RunConfig(), events)
    agent = FixtureAgent(llm=llm, tools=make_tools(workspace, list(task.allowed_files), events, 5))
    with pytest.raises(BudgetExceeded):
        agent.chat("Fix this")
    assert snapshot(workspace) == before


def test_completion_claim_does_not_override_verifier(tmp_path, monkeypatch):
    task = TASKS[0]
    workspace, before = candidate(task, tmp_path)
    monkeypatch.chdir(workspace)
    agent = FixtureAgent(llm=ScriptedLLM([LLMResponse(content="Everything fixed")]), tools=[])
    assert agent.chat("Fix this") == "Everything fixed"
    assert not verify(task, workspace, tmp_path, before, 5)["passed"]


def test_test_environment_drops_credentials_and_events_redact_escaped_secrets(tmp_path, monkeypatch):
    secret = 'private-token-"with\\escape'
    monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    monkeypatch.setenv("PYTHONSTARTUP", "untrusted.py")
    assert "DEEPSEEK_API_KEY" not in candidate_environment(tmp_path)
    assert "PYTHONSTARTUP" not in candidate_environment(tmp_path)
    events = Events(tmp_path / "trace", "test")
    events.emit("error", nested={"message": secret})
    assert json.loads((tmp_path / "trace").read_text())["nested"]["message"] == "[REDACTED]"


def test_new_tool_instances_do_not_share_task_memory(tmp_path):
    first = make_tools(tmp_path, [], Events(tmp_path / "a", "a"), 5)
    second = make_tools(tmp_path, [], Events(tmp_path / "b", "b"), 5)
    todo_a = next(tool.inner for tool in first if tool.name == "todo_write")
    todo_b = next(tool.inner for tool in second if tool.name == "todo_write")
    todo_a.execute(tasks=[{"content": "task A", "status": "pending"}])
    assert "task A" in todo_a.render()
    assert todo_b.render() == ""


@pytest.mark.parametrize("timed_out", [False, True])
def test_live_job_excludes_oracle_and_timeout_still_writes_report(tmp_path, monkeypatch, timed_out):
    def fake_worker(command, cwd, timeout, stdout_path, stderr_path, env):
        job_path = stdout_path.parent / "job.json"
        job = json.loads(job_path.read_text(encoding="utf-8"))
        assert "oracle_edits" not in job
        assert "hidden_tests" not in json.dumps(job)
        assert not (cwd / "_target_tests").exists()
        (job_path.parent / "worker-result.json").write_text(json.dumps({"status": "completed", "metrics": None}))
        return {"timed_out": timed_out, "returncode": 0, "seconds": 0.1}

    monkeypatch.setattr("evals.runner.run_process", fake_worker)
    report = run_task(TASKS[0], RunConfig(mode="live"), tmp_path)
    assert not report["accepted"]
    assert report["status"] == ("timeout" if timed_out else "failed_verification")
    assert (tmp_path / report["run_id"] / "report.json").exists()
    assert (tmp_path / report["run_id"] / "patch.diff").exists()


def test_partial_trace_after_termination_does_not_break_final_event(tmp_path):
    path = tmp_path / "trace"
    events = Events(path, "test")
    events.emit("start")
    with path.open("a") as stream:
        stream.write('{"sequence":2,"event":')
    events.emit("finished")
    last = json.loads(path.read_text().splitlines()[-1])
    assert last["sequence"] == 2
    assert last["event"] == "finished"
