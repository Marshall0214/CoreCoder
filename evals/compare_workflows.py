"""Interleaved, frozen-source comparison of single patch and schema feedback workflows."""

import argparse
import json
import statistics
from dataclasses import replace
from pathlib import Path

from .runner import digest, implementation_metadata, run_task, snapshot, write_summary
from .schema import RunConfig, load_suite


def schedule(tasks, repeat):
    if not tasks or repeat < 1:
        raise ValueError("Comparison needs tasks and positive repetitions")
    for repetition in range(1, repeat + 1):
        for index, task in enumerate(tasks):
            arms = ("single-patch", "schema-feedback")
            if (repetition + index) % 2 == 0:
                arms = tuple(reversed(arms))
            for arm in arms:
                yield repetition, task, arm


def aggregate(reports):
    known = [r["metrics"]["budget_accounted_tokens"] for r in reports
             if r.get("metrics") and r["metrics"].get("budget_accounted_tokens") is not None
             and r["metrics"].get("missing_usage_calls", 0) == 0]
    seconds = [r["seconds"] for r in reports]
    checks = [r.get("worker", {}).get("public_checks", {}) for r in reports]
    calls = [r["metrics"]["llm_calls"] for r in reports if r.get("metrics")]
    return {"runs": len(reports), "accepted": sum(r["accepted"] for r in reports),
            "token_total": sum(known) if len(known) == len(reports) else None,
            "known_token_subtotal": sum(known), "unknown_token_runs": len(reports) - len(known),
            "calls_total": sum(calls) if len(calls) == len(reports) else None,
            "seconds_total": round(sum(seconds), 4),
            "seconds_mean": round(statistics.mean(seconds), 4) if seconds else None,
            "seconds_median": round(statistics.median(seconds), 4) if seconds else None,
            "valid_generation_runs": sum(c.get("generation_status") == "valid" for c in checks),
            "valid_review_runs": sum(c.get("review_status") == "valid" for c in checks),
            "retained_check_runs": sum(bool(c.get("accepted_tests")) for c in checks),
            "feedback_runs": sum(r.get("worker", {}).get("feedback_attempts", 0) > 0 for r in reports),
            "final_public_pass_runs": sum(c.get("final", c.get("candidate", {})).get("passed") is True for c in checks),
            "statuses": {name: sum(r["status"] == name for r in reports) for name in sorted({r["status"] for r in reports})}}


def run_comparison(tasks, configs, output, repeat=3):
    items = list(schedule(tasks, repeat))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)  # Never overwrite or selectively resume a batch.
    source = implementation_metadata()
    fixtures = {task.task_id: digest(snapshot(task.root)) for task in tasks}
    freeze = {"implementation": source, "fixtures": fixtures, "repeat": repeat,
              "configs": {arm: config.to_dict() for arm, config in configs.items()},
              "schedule": [{"repetition": rep, "task_id": task.task_id, "arm": arm} for rep, task, arm in items]}
    (output / "freeze.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=2), encoding="utf-8")
    reports = {arm: [] for arm in configs}
    state = {"completed": False, "planned_runs": len(items), "stop_reason": None,
             "model_digests": [],
             "comparison_scope": "whole workflows; different call opportunities; not a retrieval-only effect"}

    def unchanged():
        current = implementation_metadata()
        if current["source_hash"] != source["source_hash"]:
            raise ValueError("Frozen implementation changed")
        if current["dependencies"] != source["dependencies"]:
            raise ValueError("Frozen dependencies changed")
        if any(digest(snapshot(task.root)) != fixtures[task.task_id] for task in tasks):
            raise ValueError("Frozen task fixture changed")

    def persist():
        state["arms"] = {arm: aggregate(rows) for arm, rows in reports.items()}
        state["tasks"] = {task.task_id: {arm: aggregate([r for r in rows if r["task_id"] == task.task_id])
                                        for arm, rows in reports.items()} for task in tasks}
        state["run_ids"] = {arm: [r["run_id"] for r in rows] for arm, rows in reports.items()}
        (output / "comparison.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    persist()
    try:
        for rep, task, arm in items:
            unchanged()
            report = run_task(task, configs[arm], output / arm, repetition=rep)
            reports[arm].append(report)
            for stage in ("ollama_before", "ollama_after"):
                runtime = (report.get("worker", {}).get(stage) or {}).get("loaded", {})
                for model in runtime.get("models", []):
                    if model.get("name", model.get("model")) == configs[arm].model and model.get("digest"):
                        state["model_digests"] = sorted(set(state["model_digests"]) | {model["digest"]})
            persist()
            print(f"round={rep} task={task.task_id} arm={arm}: {report['status']}", flush=True)
            unchanged()
            if len(state["model_digests"]) > 1:
                raise ValueError("Local model digest changed")
            if report.get("implementation", {}).get("source_hash") != source["source_hash"]:
                raise ValueError("Run did not record the frozen implementation")
            if report["status"] == "cancelled":
                state["stop_reason"] = "cancelled"
                break
        else:
            state["completed"] = True
    except KeyboardInterrupt:
        state["stop_reason"] = "cancelled"
    except Exception as exc:  # noqa: BLE001 - preserve partial experiment artifacts on orchestration errors
        state["stop_reason"] = f"{type(exc).__name__}: {exc}"
    finally:
        for arm, rows in reports.items():
            if rows:
                write_summary(rows, output / arm)
        persist()
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=Path(__file__).parent / "fixtures" / "localization-v1")
    parser.add_argument("--output", type=Path, required=True, help="New directory; existing batches are never overwritten")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--model", default="qwen3.5:27b")
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    args = parser.parse_args()
    from corecoder.config import _load_dotenv

    _load_dotenv()
    config = RunConfig(mode="pipeline", model=args.model, base_url=args.base_url, reasoning_effort="none",
                       search_backend="keyword", evidence_order="path", patch_policy="contract-coverage")
    configs = {"single-patch": config, "schema-feedback": replace(config, mode="contract-feedback",
                                                                  public_check_policy="contract-schema")}
    state = run_comparison(load_suite(args.suite), configs, args.output, args.repeat)
    print(args.output.resolve() / "comparison.json", flush=True)
    return 0 if state["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
