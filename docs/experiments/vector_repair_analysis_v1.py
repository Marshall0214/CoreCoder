"""Analyze completed runs only; reference-edit labels remain outside repair workers."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from docs.experiments.vector_repair_v1 import STRATEGIES
from evals.retrieval_eval import coverage
from evals.runner import DEFAULT_SUITE, reference_edits
from evals.schema import load_suite


def analyze(path):
    experiment = json.loads((path / "experiment.json").read_text(encoding="utf-8"))
    runs = experiment["runs"]
    tasks = {t.task_id: t for s in (DEFAULT_SUITE, DEFAULT_SUITE / "localization-v1",
                                   DEFAULT_SUITE / "retrieval-overlap-v1") for t in load_suite(s)}
    keys = [(r["task_id"], r["strategy"]) for r in runs]
    if not experiment["complete"] or len(keys) != 33 or set(keys) != {(t, s) for t in tasks for s in STRATEGIES}:
        raise ValueError("Only analyze the complete 33-run matrix")
    summary = {}
    for strategy in STRATEGIES:
        group = [r for r in runs if r["strategy"] == strategy]
        metrics = [r["worker"].get("metrics") for r in group]
        known = all(m is not None and m["missing_usage_calls"] == 0 for m in metrics)
        summary[strategy] = {"passed": sum(r["accepted"] for r in group), "runs": len(group),
                             "status_counts": dict(Counter(r["status"] for r in group)),
                             "usage_complete": known,
                             "repair_tokens": sum(m["budget_accounted_tokens"] for m in metrics) if known else None,
                             "llm_calls": sum(m["llm_calls"] for m in metrics) if all(metrics) else None,
                             "seconds": sum(r["seconds"] for r in group)}
    rows = []
    for task_id, task in tasks.items():
        group = {r["strategy"]: r for r in runs if r["task_id"] == task_id}
        targets = sorted({edit["file"] for edit in reference_edits(task)})
        hashes = {s: hashlib.sha256(json.dumps(group[s]["worker"].get("evidence_manifest"),
                                               sort_keys=True).encode()).hexdigest() for s in STRATEGIES}
        rows.append({"task_id": task_id, "targets": targets,
                     "same_ordered_evidence": len(set(hashes.values())) == 1,
                     "strategies": {s: {"status": group[s]["status"],
                                        "selected_paths": group[s]["packing"]["selected_paths"],
                                        "selected_file_recall": coverage(group[s]["packing"]["selected_paths"], targets)["recall"],
                                        "evidence_chars": group[s]["packing"]["evidence_chars"],
                                        "prompt_hash": group[s]["worker"].get("prompt_hash"),
                                        "tokens": (group[s]["worker"].get("metrics") or {}).get("budget_accounted_tokens")}
                                    for s in STRATEGIES}})
    result = {"protocol": "vector-repair-analysis-v1", "complete": True,
              "experiment_sha256": hashlib.sha256((path / "experiment.json").read_bytes()).hexdigest(),
              "summary": summary, "rows": rows,
              "limitations": "Single repeat on synthetic development tasks; file recall is an incomplete proxy; no significance claim",
              "embedding_cost": "Historical retrieval batch: 4104 tokens, 22 calls; shared once, no new embedding calls"}
    (path / "matrix.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.path)["summary"], indent=2))


if __name__ == "__main__":
    main()
