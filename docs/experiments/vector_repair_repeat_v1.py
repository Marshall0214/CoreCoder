"""Three fresh paired repeats of the frozen BM25/Dense repair protocol."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

from docs.experiments import vector_repair_v1 as original
from evals.process import run_process
from evals.runner import digest, snapshot, verify

STRATEGIES = ("bm25", "dense")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schedule(task_ids):
    return [{"repetition": repetition, "task_id": task_id,
             "strategies": list(STRATEGIES if (index + repetition) % 2 else STRATEGIES[::-1])}
            for repetition in range(1, 4) for index, task_id in enumerate(task_ids)]


def validate_order(order, task_ids):
    if order != schedule(task_ids):
        raise ValueError("Expected the fixed three-repeat paired execution order")


def inputs(source, output):
    prior = json.loads((source / "protocol.json").read_text(encoding="utf-8"))
    if (prior["protocol"] != "vector-repair-v1" or prior["expected_runs"] != 33
            or prior["engine_hash"] != original.ENGINE or prior["model_digest"] != original.MODEL_DIGEST
            or prior["config"] != original.config().to_dict()
            or prior["adapter_hash"] != sha(Path(original.__file__))
            or prior["observations_sha256"] != sha(source / "observations.json")):
        raise ValueError("Previous frozen protocol or adapter changed")
    tasks, prepared, provenance = original.prepare(source / "observations.json", output)
    for task in tasks:
        expected = prior["task_hashes"][task.task_id]
        actual = {"workspace": digest(snapshot(task.root / "workspace")),
                  "manifest": sha(task.root / "task.json"), "grader": digest(snapshot(task.root / "hidden_tests"))}
        if expected != actual:
            raise ValueError("Frozen task or grader changed")
    protocol = {"protocol": "vector-repair-repeat-v1", "development_only": True, "benchmark_eligible": False,
                "repetitions": 3, "expected_runs": 66, "historical_runs_included": False,
                "new_embedding_calls": 0, "config": prior["config"], "packing": prior["packing"],
                "engine_hash": prior["engine_hash"], "model_digest": prior["model_digest"],
                "task_hashes": prior["task_hashes"], "source_protocol_sha256": sha(source / "protocol.json"),
                "source_protocol_path": str((source / "protocol.json").resolve()),
                "adapter_files": {str(Path(original.__file__).relative_to(original.ROOT).as_posix()): sha(Path(original.__file__)),
                                  str(Path(__file__).relative_to(original.ROOT).as_posix()): sha(Path(__file__))},
                "order": schedule([t.task_id for t in tasks]), **provenance}
    return prepared, protocol


def validate_runtime(protocol, prepared):
    original.check_identity(original.config())
    for name, expected in protocol["adapter_files"].items():
        if sha(original.ROOT / name) != expected:
            raise ValueError("Frozen experiment adapter changed")
    for task, _ in prepared:
        expected = protocol["task_hashes"][task.task_id]
        if (digest(snapshot(task.root / "workspace")) != expected["workspace"]
                or sha(task.root / "task.json") != expected["manifest"]
                or digest(snapshot(task.root / "hidden_tests")) != expected["grader"]):
            raise ValueError("Task source, manifest or grader changed during repeats")


def branch(task, strategy, repetition, evidence, packing, current, output):
    root = output / f"repeat-{repetition}" / task.task_id / strategy
    root.mkdir(parents=True, exist_ok=False)
    workspace = root / "workspace"
    shutil.copytree(task.root / "workspace", workspace)
    before = snapshot(workspace)
    job = {"workspace": str(workspace.resolve()), "description": task.description,
           "allowed_files": list(task.allowed_files), "evidence": evidence, "config": current.to_dict()}
    job_path = root / "job.json"
    job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(original.ROOT), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    started = time.perf_counter()
    process = run_process([sys.executable, "-m", "docs.experiments.vector_repair_v1", "--worker",
                           str(job_path.resolve())], workspace, current.wall_timeout,
                          root / "worker.stdout.txt", root / "worker.stderr.txt", env)
    result_path = root / "worker-result.json"
    worker = (json.loads(result_path.read_text(encoding="utf-8"))
              if result_path.exists() and process["returncode"] == 0 and not process["timed_out"]
              else {"status": "timeout" if process["timed_out"] else "agent_error", "metrics": None})
    verification = verify(task, workspace, root, before, current.test_timeout)
    accepted = worker["status"] == "completed" and verification["passed"]
    row = {"task_id": task.task_id, "strategy": strategy, "repetition": repetition,
           "packing": packing, "worker": worker, "verification": verification, "accepted": accepted,
           "process": process, "seconds": time.perf_counter() - started, "artifacts": str(root.resolve()),
           "status": "passed" if accepted else ("failed_verification" if worker["status"] == "completed"
                                                else worker["status"])}
    (root / "report.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
    return row


def analyze(report):
    protocol, runs = report["protocol"], report["runs"]
    task_ids = list(protocol["task_hashes"])
    validate_order(protocol["order"], task_ids)
    keys = [(r["repetition"], r["task_id"], r["strategy"]) for r in runs]
    expected = {(rep, task, strategy) for rep in range(1, 4) for task in task_ids for strategy in STRATEGIES}
    if not report["complete"] or len(keys) != 66 or set(keys) != expected:
        raise ValueError("Analyze only the complete 66-run paired matrix")
    summary = {}
    for strategy in STRATEGIES:
        group = [r for r in runs if r["strategy"] == strategy]
        metrics = [r["worker"].get("metrics") for r in group]
        known = all(m is not None and m["missing_usage_calls"] == 0 for m in metrics)
        summary[strategy] = {"passed": sum(r["accepted"] for r in group), "runs": len(group),
                             "by_repeat": [sum(r["accepted"] for r in group if r["repetition"] == rep)
                                           for rep in range(1, 4)],
                             "status_counts": dict(Counter(r["status"] for r in group)),
                             "usage_complete": known,
                             "repair_tokens": sum(m["budget_accounted_tokens"] for m in metrics) if known else None,
                             "llm_calls": sum(m["llm_calls"] for m in metrics) if all(metrics) else None}
    pairs, tasks = Counter(), []
    for task_id in task_ids:
        group = {s: sorted([r for r in runs if r["task_id"] == task_id and r["strategy"] == s],
                           key=lambda r: r["repetition"]) for s in STRATEGIES}
        for baseline, dense in zip(group["bm25"], group["dense"]):
            pairs[("both_pass" if baseline["accepted"] and dense["accepted"] else
                   "dense_only" if dense["accepted"] else
                   "bm25_only" if baseline["accepted"] else "both_fail")] += 1
        prompt_stable = all(len({r["worker"].get("prompt_hash") for r in group[s]}) == 1
                            and all(r["worker"].get("prompt_hash") for r in group[s]) for s in STRATEGIES)
        tasks.append({"task_id": task_id, "prompt_stable_across_repeats": prompt_stable,
                      "strategies": {s: {"statuses": [r["status"] for r in group[s]],
                                         "passed": sum(r["accepted"] for r in group[s]),
                                         "tokens": [(r["worker"].get("metrics") or {}).get("budget_accounted_tokens")
                                                    for r in group[s]]} for s in STRATEGIES}})
    return {"summary": summary, "paired_outcomes": dict(pairs), "tasks": tasks,
            "limitation": "Repeated deterministic prompts on development tasks; repeats are not independent unseen defects",
            "historical_runs_included": False, "new_embedding_calls": 0}


def run(source, output, validate_only=False):
    prepared, protocol = inputs(source, output)
    validate_runtime(protocol, prepared)
    if validate_only:
        print("Validated: 11 tasks, 3 fresh repeats, 66 patch branches, zero embedding calls")
        return
    output.mkdir(parents=True, exist_ok=False)
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    shutil.copyfile(source / "observations.json", output / "observations.json")
    report = {"protocol": protocol, "complete": False, "runs": []}

    def save():
        (output / "experiment.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    save()
    cases = {t.task_id: (t, branches) for t, branches in prepared}
    for block in protocol["order"]:
        task, branches = cases[block["task_id"]]
        for strategy in block["strategies"]:
            validate_runtime(protocol, prepared)
            evidence, packing = branches[strategy]
            row = branch(task, strategy, block["repetition"], evidence, packing, original.config(), output)
            report["runs"].append(row)
            save()
            print(f'{block["repetition"]}/3 {task.task_id} {strategy}: {row["status"]}', flush=True)
    validate_runtime(protocol, prepared)
    report["complete"] = len(report["runs"]) == 66
    matrix = analyze(report)
    save()
    matrix["experiment_sha256"] = sha(output / "experiment.json")
    (output / "matrix.json").write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    print(json.dumps(matrix["summary"], indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    run(args.source.resolve(), args.output.resolve(), args.validate_only)


if __name__ == "__main__":
    main()
