import copy

import pytest

from docs.experiments.vector_repair_repeat_v1 import analyze, schedule, validate_order


def report():
    tasks = [f"task-{i}" for i in range(11)]
    runs = []
    for repetition in range(1, 4):
        for task in tasks:
            for strategy in ("bm25", "dense"):
                accepted = task == "task-0" or (task == "task-1" and strategy == "dense")
                runs.append({"repetition": repetition, "task_id": task, "strategy": strategy,
                             "accepted": accepted, "status": "passed" if accepted else "failed_verification",
                             "worker": {"prompt_hash": f"{task}-{strategy}",
                                        "metrics": {"missing_usage_calls": 0, "budget_accounted_tokens": 100,
                                                    "llm_calls": 1}}})
    return {"protocol": {"task_hashes": {t: {} for t in tasks}, "order": schedule(tasks)},
            "complete": True, "runs": runs}


def test_schedule_balances_pairs_and_rejects_modified_order():
    tasks = [f"task-{i}" for i in range(11)]
    order = schedule(tasks)
    assert len(order) == 33
    assert all(set(row["strategies"]) == {"bm25", "dense"} for row in order)
    assert order[0]["strategies"] != order[11]["strategies"]
    modified = copy.deepcopy(order)
    modified[0]["strategies"] = ["dense", "dense"]
    with pytest.raises(ValueError, match="fixed"):
        validate_order(modified, tasks)


def test_analysis_counts_only_new_paired_repeats():
    matrix = analyze(report())
    assert matrix["summary"]["bm25"]["passed"] == 3
    assert matrix["summary"]["dense"]["passed"] == 6
    assert matrix["summary"]["dense"]["by_repeat"] == [2, 2, 2]
    assert matrix["paired_outcomes"] == {"both_pass": 3, "dense_only": 3, "both_fail": 27}
    assert matrix["summary"]["dense"]["repair_tokens"] == 3300
    assert all(t["prompt_stable_across_repeats"] for t in matrix["tasks"])
    assert matrix["historical_runs_included"] is False


@pytest.mark.parametrize("mutation", ["incomplete", "missing", "duplicate"])
def test_incomplete_or_duplicate_matrix_rejected(mutation):
    data = report()
    if mutation == "incomplete":
        data["complete"] = False
    elif mutation == "missing":
        data["runs"].pop()
    else:
        data["runs"][-1] = data["runs"][0]
    with pytest.raises(ValueError, match="complete"):
        analyze(data)


def test_missing_usage_is_unknown_and_prompt_drift_visible():
    data = report()
    data["runs"][0]["worker"]["metrics"] = None
    data["runs"][0]["worker"]["prompt_hash"] = "changed"
    matrix = analyze(data)
    assert matrix["summary"]["bm25"]["repair_tokens"] is None
    assert matrix["summary"]["bm25"]["usage_complete"] is False
    assert matrix["tasks"][0]["prompt_stable_across_repeats"] is False
