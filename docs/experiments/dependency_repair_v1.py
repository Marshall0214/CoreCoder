"""Fresh 2x2 retrieval/dependency comparison after a label-free evidence audit."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from docs.experiments import vector_repair_repeat_v1 as repeat
from docs.experiments import vector_repair_v1 as original
from docs.experiments.dependency_context_v1 import expand

POLICIES = ("bm25-seeds", "bm25-imports", "dense-seeds", "dense-imports")


def evidence_hash(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def prepare(source, output):
    prepared, parent = repeat.inputs(source, output)
    cases = {}
    audit = []
    for task, branches in prepared:
        policies = {}
        for strategy in repeat.STRATEGIES:
            seeds, metadata = branches[strategy]
            policies[strategy + "-seeds"] = (seeds, {**metadata, "policy": "seeds", "dependency_depth": 0})
            policies[strategy + "-imports"] = expand(task.root / "workspace", task.allowed_files, seeds, metadata)
        cases[task.task_id] = (task, policies)
        audit.append({"task_id": task.task_id,
                      "policies": {p: {"metadata": metadata, "evidence_hash": evidence_hash(rows), "evidence": rows}
                                   for p, (rows, metadata) in policies.items()}})
    adapters = dict(parent["adapter_files"])
    from docs.experiments import dependency_context_v1

    for path in (Path(dependency_context_v1.__file__), Path(__file__)):
        adapters[path.relative_to(original.ROOT).as_posix()] = repeat.sha(path)
    protocol = {**parent, "protocol": "dependency-repair-v1", "repetitions": 1, "expected_runs": 44,
                "adapter_files": adapters,
                "packing": "frozen top-5 whole-file seeds; optional appended public imports depth2; 6000 chars total",
                "comparison": "fresh 2x2 retrieval (BM25/Dense) x context (seeds/imports); no historical repair reuse",
                "order": [{"task_id": task_id, "policies": list(POLICIES[i % 4:] + POLICIES[:i % 4])}
                          for i, task_id in enumerate(cases)],
                "audit_sha256": evidence_hash(audit)}
    return prepared, cases, audit, protocol


def analyze(report):
    runs = report["runs"]
    task_ids = list(report["protocol"]["task_hashes"])
    keys = [(r["task_id"], r["strategy"]) for r in runs]
    if not report["complete"] or len(keys) != 44 or set(keys) != {(t, p) for t in task_ids for p in POLICIES}:
        raise ValueError("Expected complete fresh 44-run factorial matrix")
    summary = {}
    for policy in POLICIES:
        group = [r for r in runs if r["strategy"] == policy]
        metrics = [r["worker"].get("metrics") for r in group]
        known = all(m and m["missing_usage_calls"] == 0 for m in metrics)
        summary[policy] = {"passed": sum(r["accepted"] for r in group), "runs": len(group),
                           "status_counts": dict(Counter(r["status"] for r in group)),
                           "repair_tokens": sum(m["budget_accounted_tokens"] for m in metrics) if known else None,
                           "usage_complete": bool(known)}
    tasks, effects = [], {s: Counter() for s in repeat.STRATEGIES}
    for task_id in task_ids:
        group = {r["strategy"]: r for r in runs if r["task_id"] == task_id}
        for strategy in repeat.STRATEGIES:
            before, after = (group[strategy + "-" + p]["accepted"] for p in ("seeds", "imports"))
            effects[strategy]["both_pass" if before and after else "imports_only" if after
                              else "seeds_only" if before else "both_fail"] += 1
        tasks.append({"task_id": task_id, "policies": {p: {"status": r["status"], "tokens":
                      (r["worker"].get("metrics") or {}).get("budget_accounted_tokens"),
                      "selected_paths": r["packing"]["selected_paths"], "added": r["packing"].get("added", []),
                      "error": r["worker"].get("error")} for p, r in group.items()}})
    return {"summary": summary, "dependency_paired_effects": {s: dict(v) for s, v in effects.items()},
            "tasks": tasks, "historical_runs_included": False, "new_embedding_calls": 0,
            "limitation": "One repeat on 11 synthetic development tasks; not held-out or statistical evidence"}


def run(source, output, audit_only=False):
    prepared, cases, audit, protocol = prepare(source, output)
    repeat.validate_runtime(protocol, prepared)
    output.mkdir(parents=True, exist_ok=False)
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    (output / "evidence-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if audit_only:
        print("Saved label-free evidence audit for 11 tasks / 4 policies; zero model calls")
        return
    report = {"protocol": protocol, "complete": False, "runs": []}

    def save():
        (output / "experiment.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    save()
    for block in protocol["order"]:
        task, policies = cases[block["task_id"]]
        for policy in block["policies"]:
            repeat.validate_runtime(protocol, prepared)
            evidence, metadata = policies[policy]
            row = repeat.branch(task, policy, 1, evidence, metadata, original.config(), output)
            report["runs"].append(row)
            save()
            print(f'{task.task_id} {policy}: {row["status"]}', flush=True)
    repeat.validate_runtime(protocol, prepared)
    report["complete"] = len(report["runs"]) == 44
    matrix = analyze(report)
    save()
    matrix["experiment_sha256"] = repeat.sha(output / "experiment.json")
    (output / "matrix.json").write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    print(json.dumps(matrix["summary"], indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    run(args.source.resolve(), args.output.resolve(), args.audit_only)


if __name__ == "__main__":
    main()
