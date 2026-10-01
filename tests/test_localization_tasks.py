"""Offline admission checks for the synthetic localization development suite."""

import json
import shutil

import pytest

from evals.runner import DEFAULT_SUITE, reference_edits, run_task, snapshot, verify
from evals.schema import RunConfig, load_suite

SUITE = DEFAULT_SUITE / "localization-v1"
TASKS = load_suite(SUITE)
EXPECTED_IDS = {"artifact-routing", "checkout-rounding", "event-replay", "job-deadline", "pagination-cursor"}


def test_default_regression_suite_is_not_expanded():
    assert {task.task_id for task in load_suite(DEFAULT_SUITE)} == {
        "falsey-overrides", "inclusive-date", "retry-policy", "tenant-cache", "timeout-units",
    }
    assert {task.task_id for task in TASKS} == EXPECTED_IDS


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.task_id)
def test_new_tasks_fail_before_repair_and_pass_reference_and_scripted(task, tmp_path):
    broken = run_task(task, RunConfig(), tmp_path)
    assert broken["status"] == "failed_verification", broken
    assert not broken["verification"]["target"]["passed"]
    assert broken["verification"]["regression"]["passed"]
    for mode in ("reference", "scripted"):
        repaired = run_task(task, RunConfig(mode=mode), tmp_path)
        assert repaired["accepted"], repaired
        assert repaired["fixture_hash"] == broken["fixture_hash"]
        assert not repaired["benchmark_eligible"]
        assert len(repaired["verification"]["changed_files"]) == 2
        if mode == "scripted":
            job_path = tmp_path / repaired["run_id"] / "job.json"
            job = json.loads(job_path.read_text(encoding="utf-8"))
            assert "relevant_files" not in job
            assert "evaluation.json" not in json.dumps(job)
            assert not (job_path.parent / "workspace" / "evaluation.json").exists()


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.task_id)
def test_each_individual_reference_edit_is_insufficient(task, tmp_path):
    edits = reference_edits(task)
    assert len(edits) == 2
    for index, edit in enumerate(edits):
        run_root = tmp_path / str(index)
        workspace = run_root / "workspace"
        shutil.copytree(task.root / "workspace", workspace)
        before = snapshot(workspace)
        path = workspace / edit["file"]
        source = path.read_text(encoding="utf-8")
        assert source.count(edit["old"]) == 1
        path.write_text(source.replace(edit["old"], edit["new"]), encoding="utf-8")
        result = verify(task, workspace, run_root, before, 5)
        assert not result["passed"], (task.task_id, edit["file"], result)
        assert not result["target"]["passed"]
        assert result["regression"]["passed"]
        assert not result["scope_violations"]


@pytest.mark.parametrize("task", TASKS, ids=lambda task: task.task_id)
def test_parent_annotations_have_valid_file_labels(task):
    annotations = json.loads((task.root / "evaluation.json").read_text(encoding="utf-8"))
    assert annotations["purpose"] == "development"
    assert annotations["source"] == "synthetic"
    for name in annotations["relevant_files"]:
        assert (task.root / "workspace" / name).is_file()
    assert set(annotations["reference_changed_files"]) <= set(task.allowed_files)
    assert not (task.root / "workspace" / "reference.json").exists()
    assert not (task.root / "workspace" / "hidden_tests").exists()
