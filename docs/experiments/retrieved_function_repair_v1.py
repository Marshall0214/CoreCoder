"""Frozen BM25 raw-chunk versus function/dependency evidence on seven real cases."""

import argparse
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

from docs.experiments import real_retrieval_audit_v1 as audit
from docs.experiments import retrieved_functions_v1 as functions
from docs.experiments.vector_repair_v1 import check_identity, config
from evals.process import run_process
from evals.real_admission import checked_groups
from evals.real_tasks import admitted_case, verify
from evals.runner import digest, snapshot
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.symbol_context import apply_symbol_patch
from evals.symbol_patch import SYMBOL_SYSTEM
from evals.worker import TracedLLM

POLICIES = ("raw-chunks", "functions")
OBS_SHA = "095f4b7f601de2db7b4036aed23f7737a0178acb227fbf67be6c18fd63da5083"


def prepare(source, output):
    if audit.sha(source / "observations.json") != OBS_SHA:
        raise ValueError("Expected frozen real retrieval observations")
    prior = json.loads((source / "protocol.json").read_text(encoding="utf-8"))
    if prior["protocol"] != "real-retrieval-audit-v1" or prior["engine_hash"] != audit.ENGINE:
        raise ValueError("Wrong retrieval protocol")
    names = {"candidates.json": "original", "crossfile-candidates.json": "crossfile",
             "expansion-candidates-v1.json": "expansion"}
    admissions = {names[Path(row["catalog"]).name]: Path(row["admission_path"]) for row in prior["inputs"]}
    cases = audit.public_cases(admissions)
    if output.exists() or any(output.resolve().is_relative_to(c["before"].parent.resolve()) for c in cases):
        raise ValueError("Use a fresh output outside admitted sources")
    observations = json.loads((source / "observations.json").read_text(encoding="utf-8"))
    if [r["task_id"] for r in observations] != [c["task_id"] for c in cases]:
        raise ValueError("Frozen task order mismatch")
    bundles = []
    for case, observation in zip(cases, observations):
        if observation["query"] != case["description"] + " contract contracts":
            raise ValueError("Public query changed")
        selected, metadata = functions.evidence(case["before"], case["allowed_files"], observation)
        bundles.append({"task_id": case["task_id"], "policies": {
            "raw-chunks": {"evidence": observation["packing"]["bm25"]["full_chunks"]["selected"],
                           "metadata": {"max_chars": 6000}},
            "functions": {"evidence": selected, "metadata": metadata}}})
    return cases, bundles


def worker(path):
    job = json.loads(path.read_text(encoding="utf-8"))
    events = Events(path.parent / "trace.jsonl", path.parent.name)
    result, llm = {"status": "agent_error"}, None
    try:
        check_identity(config())
        workspace = Path(job["workspace"])
        fragments = [{k: r.get(k) for k in ("path", "start_line", "end_line", "content_hash", "content", "symbol")}
                     for r in job["evidence"]]
        messages = [{"role": "system", "content": SYMBOL_SYSTEM}, {"role": "user", "content": json.dumps(
            {"description": job["description"], "allowed_files": job["allowed_files"], "fragments": fragments}, ensure_ascii=False)}]
        result["prompt_hash"] = hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()
        events.emit("fragment_patch_prepared", evidence_chars=sum(len(r["content"]) for r in fragments),
                    files=[{k: v for k, v in r.items() if k != "content"} for r in fragments])
        current = config()
        llm = BudgetLLM(TracedLLM(current.model, "ollama", current.base_url, events=events,
                                 temperature=0, reasoning_effort="none", max_tokens=2048, timeout=60), current, events)
        response = llm.chat(messages, tools=[])
        (path.parent / "response.txt").write_text(events.clean(response.content), encoding="utf-8")
        if response.tool_calls:
            raise ValueError("Tool calls are outside the single-patch protocol")
        try:
            result["edited_files"] = apply_symbol_patch(response.content, workspace, job["allowed_files"], fragments)
            result["status"] = "completed"
        except (ValueError, TypeError, KeyError) as exc:
            result.update(status="invalid_patch", error=f"{type(exc).__name__}: {exc}")
        check_identity(current)
    except BudgetExceeded as exc:
        result.update(status="budget_exceeded", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - preserve failed branches
        result.update(status="agent_error", error=f"{type(exc).__name__}: {exc}")
    finally:
        result["metrics"] = llm.metrics() if llm else None
        (path.parent / "worker-result.json").write_text(json.dumps(events.clean(result), indent=2), encoding="utf-8")


def run(source, output, audit_only=False):
    cases, bundles = prepare(source, output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "evidence.json").write_text(json.dumps(bundles, ensure_ascii=False, indent=2), encoding="utf-8")
    protocol = {"protocol": "retrieved-function-repair-v1", "development_only": True, "expected_runs": 14,
                "observations_sha256": OBS_SHA, "evidence_sha256": audit.sha(output / "evidence.json"),
                "config": config().to_dict(), "engine_hash": audit.ENGINE,
                "adapter_hashes": {p.relative_to(audit.ROOT).as_posix(): audit.sha(p)
                                   for p in (Path(__file__), Path(functions.__file__), Path(audit.__file__))},
                "order": [{"task_id": c["task_id"], "policies": list(POLICIES if i % 2 == 0 else POLICIES[::-1])}
                          for i, c in enumerate(cases)],
                "intervention": "complete retrieved functions plus one-hop function dependencies; raw fallback for oversized functions",
                "repair_model_digest": "7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e"}
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    # Evidence is fixed before opening any after/reference labels, even in audit mode.
    scores = []
    for case, bundle in zip(cases, bundles):
        _, spans = audit.labels(case)
        scores.append({"task_id": case["task_id"], "line_recall": {
            p: audit.span_recall(bundle["policies"][p]["evidence"], spans) for p in POLICIES}})
    (output / "coverage.json").write_text(json.dumps(scores, indent=2), encoding="utf-8")
    if audit_only:
        print(json.dumps(scores, indent=2))
        return
    check_identity(config())
    report = {"protocol": protocol, "complete": False, "runs": []}

    def save():
        (output / "experiment.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    save()
    for case, bundle, block in zip(cases, bundles, protocol["order"]):
        admitted = admitted_case(case["admission_path"], case["catalog"], case["task_id"])
        original_case, _, checks, source_root, environment = admitted
        python = Path(environment["executable"])
        for policy in block["policies"]:
            check_identity(config())
            if any(audit.sha(audit.ROOT / name) != expected for name, expected in protocol["adapter_hashes"].items()):
                raise ValueError("Frozen adapter changed")
            root = output / case["task_id"] / policy
            root.mkdir(parents=True)
            preflight = checked_groups(case["before"], checks, root / "preflight", python, 15)
            if not (preflight["Controls"]["passed"] and preflight["Target"]["assertion_failure"]
                    and not preflight["Target"]["execution_error"]):
                raise ValueError("Admitted behavior no longer reproduces")
            workspace = root / "workspace"
            shutil.copytree(case["before"], workspace)
            before = snapshot(workspace)
            if digest(before) != case["before_hash"]:
                raise ValueError("Before source changed")
            evidence = bundle["policies"][policy]["evidence"]
            job = {"workspace": str(workspace.resolve()), "description": case["description"],
                   "allowed_files": case["allowed_files"], "evidence": evidence}
            path = root / "job.json"
            path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=str(audit.ROOT), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
            process = run_process([sys.executable, "-m", "docs.experiments.retrieved_function_repair_v1", "--worker", str(path.resolve())],
                                  workspace, 600, root / "worker.stdout.txt", root / "worker.stderr.txt", env)
            result_path = root / "worker-result.json"
            result = (json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() and process["returncode"] == 0
                      and not process["timed_out"] else {"status": "timeout" if process["timed_out"] else "agent_error", "metrics": None})
            verification = verify(original_case, source_root, checks, workspace, before, case["allowed_files"], root, python, 15)
            accepted = result["status"] == "completed" and verification["passed"]
            row = {"task_id": case["task_id"], "policy": policy, "worker": result, "verification": verification,
                   "accepted": accepted, "status": "passed" if accepted else ("failed_verification" if result["status"] == "completed" else result["status"]),
                   "evidence_chars": sum(len(r["content"]) for r in evidence), "process": process}
            report["runs"].append(row)
            save()
            print(f'{case["task_id"]} {policy}: {row["status"]}', flush=True)
    check_identity(config())
    report["complete"] = len(report["runs"]) == 14
    report["summary"] = {p: {"passed": sum(r["accepted"] for r in report["runs"] if r["policy"] == p),
                              "statuses": dict(Counter(r["status"] for r in report["runs"] if r["policy"] == p)),
                              "tokens": sum((r["worker"].get("metrics") or {}).get("budget_accounted_tokens", 0)
                                            for r in report["runs"] if r["policy"] == p)} for p in POLICIES}
    save()
    print(json.dumps(report["summary"], indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(args.worker.resolve())
    elif args.source and args.output:
        run(args.source.resolve(), args.output.resolve(), args.audit_only)
    else:
        parser.error("Specify --source and --output")


if __name__ == "__main__":
    main()
