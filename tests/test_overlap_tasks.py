"""Admission and partial-repair rejection for the retrieval opportunity pilot."""

import shutil

import pytest

from evals.runner import DEFAULT_SUITE, reference_edits, run_task, snapshot, verify
from evals.schema import RunConfig, load_suite

TASK = load_suite(DEFAULT_SUITE / "retrieval-overlap-v1")[0]


def test_lifecycle_admission_and_oracle_tool_path(tmp_path):
    broken = run_task(TASK, RunConfig(), tmp_path)
    assert not broken["verification"]["target"]["passed"]
    assert broken["verification"]["regression"]["passed"]
    for mode in ("reference", "scripted"):
        repaired = run_task(TASK, RunConfig(mode=mode, search_backend="keyword"), tmp_path)
        assert repaired["accepted"], repaired
        assert len(repaired["verification"]["changed_files"]) == 3


@pytest.mark.parametrize("omitted", range(3))
def test_leaving_any_lifecycle_defect_is_rejected(tmp_path, omitted):
    workspace = tmp_path / "workspace"
    shutil.copytree(TASK.root / "workspace", workspace)
    before = snapshot(workspace)
    for index, edit in enumerate(reference_edits(TASK)):
        if index == omitted:
            continue
        path = workspace / edit["file"]
        source = path.read_text(encoding="utf-8")
        assert source.count(edit["old"]) == 1
        path.write_text(source.replace(edit["old"], edit["new"]), encoding="utf-8")
    result = verify(TASK, workspace, tmp_path, before, 5)
    assert not result["passed"]
    assert result["regression"]["passed"]
    assert not result["scope_violations"]
