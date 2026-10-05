import json
from dataclasses import replace

import pytest

from evals.compare_workflows import aggregate, run_comparison, schedule
from evals.schema import RunConfig, Task


def tasks(tmp_path):
    result = []
    for name in ("a", "b"):
        root = tmp_path / name
        root.mkdir()
        (root / "fixture.txt").write_text("initial", encoding="utf-8")
        result.append(Task(name, name, "public", ("code.py",), root))
    return result


def test_interleaving_pairs_all_tasks_and_rotates_first_arm(tmp_path):
    rows = [(rep, task.task_id, arm) for rep, task, arm in schedule(tasks(tmp_path), 3)]
    assert len(rows) == 12
    assert rows[:4] == [(1, "a", "single-patch"), (1, "a", "schema-feedback"),
                        (1, "b", "schema-feedback"), (1, "b", "single-patch")]
    assert rows[4][2] == "schema-feedback"
    assert len(set(rows)) == 12


def test_custom_policy_labels_keep_interleaved_order(tmp_path):
    rows = [(rep, task.task_id, arm) for rep, task, arm in schedule(tasks(tmp_path), 2, ('v5', 'v6'))]
    assert rows[:4] == [(1, 'a', 'v5'), (1, 'a', 'v6'), (1, 'b', 'v6'), (1, 'b', 'v5')]
    assert rows[4][2] == 'v6'


@pytest.mark.parametrize('arms', [(), ('v5',), ('v5', 'v5'), ('v4', 'v5', 'v6')])
def test_comparison_rejects_invalid_arm_sets(tmp_path, arms):
    with pytest.raises(ValueError, match='two distinct arms'):
        list(schedule(tasks(tmp_path), 1, arms))


def report(task, status="failed_verification", metrics=None):
    return {"run_id": "test-" + task.task_id, "task_id": task.task_id, "status": status,
            "accepted": status == "passed", "seconds": 2.0, "mode": "pipeline", "benchmark_eligible": True,
            "metrics": metrics, "implementation": {"source_hash": "frozen"}}


def test_missing_usage_is_unknown_not_zero(tmp_path):
    result = aggregate([report(tasks(tmp_path)[0])])
    assert result["runs"] == 1 and result["accepted"] == 0
    assert result["token_total"] is None and result["unknown_token_runs"] == 1


def configure(monkeypatch):
    monkeypatch.setattr("evals.compare_workflows.implementation_metadata",
                        lambda: {"source_hash": "frozen", "dependencies": {}})
    base = RunConfig(mode="pipeline", search_backend="keyword", patch_policy="contract-coverage")
    return {"single-patch": base, "schema-feedback": replace(base, mode="contract-feedback", public_check_policy="contract-schema")}


def test_failures_remain_in_denominator_and_batch_completes(tmp_path, monkeypatch):
    configs = configure(monkeypatch)

    def fake_run(task, config, output, repetition):
        output.mkdir(parents=True, exist_ok=True)
        return report(task, metrics={"budget_accounted_tokens": 10, "llm_calls": 1})

    monkeypatch.setattr("evals.compare_workflows.run_task", fake_run)
    output = tmp_path / "batch"
    fixtures = tasks(tmp_path)
    result = run_comparison(fixtures, configs, output, repeat=2)
    assert result["completed"] and result["planned_runs"] == 8
    assert all(arm["runs"] == 4 and arm["accepted"] == 0 for arm in result["arms"].values())
    assert (output / "freeze.json").exists()
    assert json.loads((output / "comparison.json").read_text())["completed"]
    with pytest.raises(FileExistsError):
        run_comparison(fixtures, configs, output)


def test_fixture_change_stops_batch_and_preserves_partial_result(tmp_path, monkeypatch):
    configs = configure(monkeypatch)

    def fake_run(task, config, output, repetition):
        output.mkdir(parents=True, exist_ok=True)
        (task.root / "fixture.txt").write_text("changed", encoding="utf-8")
        return report(task)

    monkeypatch.setattr("evals.compare_workflows.run_task", fake_run)
    result = run_comparison(tasks(tmp_path), configs, tmp_path / "batch", repeat=3)
    assert not result["completed"] and "fixture changed" in result["stop_reason"]
    assert sum(arm["runs"] for arm in result["arms"].values()) == 1


def test_estimated_fallback_usage_is_not_reported_as_measured_tokens(tmp_path):
    row = report(tasks(tmp_path)[0], metrics={"budget_accounted_tokens": 99, "llm_calls": 1, "missing_usage_calls": 1})
    assert aggregate([row])["token_total"] is None


@pytest.mark.parametrize("change", ["source", "model"])
def test_version_changes_stop_after_preserving_current_run(tmp_path, monkeypatch, change):
    configs = configure(monkeypatch)

    def fake_run(task, config, output, repetition):
        output.mkdir(parents=True, exist_ok=True)
        row = report(task)
        if change == "source":
            monkeypatch.setattr("evals.compare_workflows.implementation_metadata",
                                lambda: {"source_hash": "changed", "dependencies": {}})
        else:
            row["worker"] = {stage: {"loaded": {"models": [{"name": config.model, "digest": value}]}}
                             for stage, value in (("ollama_before", "old"), ("ollama_after", "new"))}
        return row

    monkeypatch.setattr("evals.compare_workflows.run_task", fake_run)
    result = run_comparison(tasks(tmp_path), configs, tmp_path / "batch", repeat=3)
    assert not result["completed"] and "changed" in result["stop_reason"]
    assert sum(arm["runs"] for arm in result["arms"].values()) == 1


def test_cancellation_keeps_partial_batch_without_reruns(tmp_path, monkeypatch):
    configs = configure(monkeypatch)

    def fake_run(task, config, output, repetition):
        output.mkdir(parents=True, exist_ok=True)
        return report(task, status="cancelled")

    monkeypatch.setattr("evals.compare_workflows.run_task", fake_run)
    result = run_comparison(tasks(tmp_path), configs, tmp_path / "batch", repeat=3)
    assert not result["completed"] and result["stop_reason"] == "cancelled"
    assert sum(arm["runs"] for arm in result["arms"].values()) == 1
