"""One-patch comparison on frozen, label-free retrieval observations."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from corecoder.retrieval.keyword import KeywordIndex
from evals.fixed_evidence import generate_patch
from evals.process import run_process
from evals.runner import DEFAULT_SUITE, digest, implementation_metadata, snapshot, verify
from evals.runtime import BudgetExceeded, BudgetLLM, Events
from evals.schema import RunConfig, load_suite
from evals.worker import TracedLLM, ollama_metadata

ROOT = Path(__file__).resolve().parents[2]
ENGINE = "c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd"
MODEL_DIGEST = "7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e"
STRATEGIES = ("bm25", "dense", "hybrid")


def config():
    return RunConfig(mode="pipeline", model="qwen3.5:27b", base_url="http://localhost:11434/v1",
                     reasoning_effort="none", token_budget=15000, wall_timeout=600,
                     search_backend="keyword", evidence_dependency_depth=0)


def check_identity(current):
    if implementation_metadata()["source_hash"] != ENGINE:
        raise ValueError("Frozen engine changed")
    metadata = ollama_metadata(current)
    if not any(m["digest"] == MODEL_DIGEST and m["name"] == current.model
               for m in metadata.get("identity", {}).get("models", [])):
        raise ValueError("Frozen repair model unavailable or changed")


def pack(workspace, allowed_files, observation, strategy, max_chars=6000, top_k=5):
    """Whole-file, rank-order packing; no dependencies, slicing, or scoring labels."""
    index = KeywordIndex(workspace, allowed_files)
    metadata = index.refresh()
    if metadata["index_hash"] != observation["index"]["index_hash"]:
        raise ValueError("Frozen retrieval corpus changed")
    chunks = {(c.path, c.start_line, c.end_line, c.content_hash) for c in index.chunks}
    ranking = observation["chunk_rankings"][strategy]
    keys = [(r["path"], r["start_line"], r["end_line"], r["content_hash"]) for r in ranking]
    if len(set(keys)) != len(keys) or any(k not in chunks for k in keys):
        raise ValueError("Invalid or duplicate frozen chunk citation")
    files = list(dict.fromkeys(r["path"] for r in ranking))
    if files != observation["rankings"][strategy]:
        raise ValueError("File ranking differs from chunk ranking")
    if strategy != "bm25" and set(keys) != chunks:
        raise ValueError("Dense/Hybrid ranking must contain every indexed chunk")
    selected, discarded, chars = [], [], 0
    for name in files[:top_k]:
        path = workspace / name
        if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("Evidence path escaped workspace")
        raw = path.read_bytes()
        expected = next(c.content_hash for c in index.chunks if c.path == name)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Evidence changed during packing")
        text = raw.decode("utf-8")
        if chars + len(text) > max_chars:
            discarded.append({"path": name, "reason": "whole_file_budget", "chars": len(text)})
            continue
        selected.append({"path": name, "content_hash": expected, "content": text})
        chars += len(text)
    return selected, {"strategy": strategy, "top_k": top_k, "max_chars": max_chars,
                      "selected_paths": [r["path"] for r in selected], "evidence_chars": chars,
                      "discarded": discarded, "index_hash": metadata["index_hash"]}


def worker(job_path):
    job = json.loads(job_path.read_text(encoding="utf-8"))
    root = job_path.parent
    events = Events(root / "trace.jsonl", root.name)
    current = RunConfig(**job["config"])
    counted = None
    result = {"status": "agent_error"}
    try:
        check_identity(current)
        counted = BudgetLLM(TracedLLM(current.model, "ollama", current.base_url, events=events,
                                     temperature=current.temperature, reasoning_effort=current.reasoning_effort,
                                     max_tokens=current.max_output_tokens, timeout=60), current, events)
        result.update(generate_patch(counted, Path(job["workspace"]), job["description"],
                                     job["allowed_files"], events, job["evidence"],
                                     protocol="vector-repair-v1", response_name="response.txt"))
        check_identity(current)
    except BudgetExceeded as exc:
        result.update(status="budget_exceeded", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - preserve every failed run
        result.update(status="agent_error", error=f"{type(exc).__name__}: {exc}")
    finally:
        result["metrics"] = counted.metrics() if counted else None
        (root / "worker-result.json").write_text(json.dumps(events.clean(result), indent=2), encoding="utf-8")


def prepare(observations_path, output):
    raw = observations_path.read_bytes()
    observations = json.loads(raw)
    tasks = [t for s in [DEFAULT_SUITE, DEFAULT_SUITE / "localization-v1",
                        DEFAULT_SUITE / "retrieval-overlap-v1"] for t in load_suite(s)]
    if len(observations) != 11 or [r["task_id"] for r in observations] != [t.task_id for t in tasks]:
        raise ValueError("Expected the frozen 11-task retrieval observations")
    output = output.resolve()
    if output.exists() or any(output.is_relative_to(t.root.resolve()) for t in tasks):
        raise ValueError("Use a fresh output directory outside task fixtures")
    prepared = []
    for task, row in zip(tasks, observations):
        if set(row) - {"task_id", "query", "index", "rankings", "chunk_rankings", "rank_seconds",
                       "vector_build_seconds", "embedding_usage_delta"}:
            raise ValueError("Unexpected observation fields; use label-free observations.json")
        if row["query"] != task.description + " contract contracts":
            raise ValueError("Frozen public query changed")
        branches = {s: pack(task.root / "workspace", task.allowed_files, row, s) for s in STRATEGIES}
        prepared.append((task, branches))
    return tasks, prepared, {"observations_sha256": hashlib.sha256(raw).hexdigest(),
                             "observations_path": str(observations_path.resolve())}


def run(observations_path, output):
    tasks, prepared, provenance = prepare(observations_path, output)
    current = config()
    check_identity(current)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(observations_path, output / "observations.json")
    protocol = {"protocol": "vector-repair-v1", "benchmark_eligible": False, "development_only": True,
                "repetitions": 1, "expected_runs": 33, "config": current.to_dict(),
                "packing": "rank-order whole files, top-5 files, 6000 chars, no dependencies",
                "engine_hash": ENGINE, "model_digest": MODEL_DIGEST,
                "adapter_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), **provenance,
                "task_hashes": {t.task_id: {"workspace": digest(snapshot(t.root / "workspace")),
                                            "manifest": hashlib.sha256((t.root / "task.json").read_bytes()).hexdigest(),
                                            "grader": digest(snapshot(t.root / "hidden_tests"))} for t in tasks},
                "order": [{"task_id": t.task_id, "strategies": list(STRATEGIES[i % 3:] + STRATEGIES[:i % 3])}
                          for i, t in enumerate(tasks)]}
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    report = {"protocol": protocol, "complete": False, "runs": []}

    def save():
        (output / "experiment.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    save()
    for block, (task, branches) in zip(protocol["order"], prepared):
        for strategy in block["strategies"]:
            check_identity(current)
            if digest(snapshot(task.root / "workspace")) != protocol["task_hashes"][task.task_id]["workspace"]:
                raise ValueError("Fixture changed between branches")
            root = output / task.task_id / strategy
            root.mkdir(parents=True, exist_ok=False)
            workspace = root / "workspace"
            shutil.copytree(task.root / "workspace", workspace)
            before = snapshot(workspace)
            evidence, packing = branches[strategy]
            job = {"workspace": str(workspace.resolve()), "description": task.description,
                   "allowed_files": list(task.allowed_files), "evidence": evidence, "config": current.to_dict()}
            job_path = root / "job.json"
            job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
            started = time.perf_counter()
            process = run_process([sys.executable, "-m", "docs.experiments.vector_repair_v1", "--worker",
                                   str(job_path.resolve())], workspace, current.wall_timeout,
                                  root / "worker.stdout.txt", root / "worker.stderr.txt", env)
            result_path = root / "worker-result.json"
            result = (json.loads(result_path.read_text(encoding="utf-8"))
                      if result_path.exists() and process["returncode"] == 0 and not process["timed_out"]
                      else {"status": "timeout" if process["timed_out"] else "agent_error", "metrics": None})
            verification = verify(task, workspace, root, before, current.test_timeout)
            accepted = result["status"] == "completed" and verification["passed"]
            row = {"task_id": task.task_id, "strategy": strategy, "packing": packing, "worker": result,
                   "verification": verification, "accepted": accepted, "process": process,
                   "status": "passed" if accepted else ("failed_verification" if result["status"] == "completed"
                                                        else result["status"]),
                   "seconds": time.perf_counter() - started, "artifacts": str(root.resolve())}
            (root / "report.json").write_text(json.dumps(row, indent=2), encoding="utf-8")
            report["runs"].append(row)
            save()
            print(f'{task.task_id} {strategy}: {row["status"]}', flush=True)
    check_identity(current)
    report["complete"] = len(report["runs"]) == 33
    report["summary"] = {s: {"passed": sum(r["accepted"] for r in report["runs"] if r["strategy"] == s),
                               "runs": 11,
                               "repair_tokens": sum((r["worker"].get("metrics") or {}).get("budget_accounted_tokens", 0)
                                                    for r in report["runs"] if r["strategy"] == s)} for s in STRATEGIES}
    save()
    print(json.dumps(report["summary"], indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", type=Path)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(args.worker.resolve())
    elif args.observations and args.output:
        if args.validate_only:
            prepare(args.observations, args.output)
            check_identity(config())
            print("Validated 11 tasks / 33 branches; zero model calls")
        else:
            run(args.observations, args.output.resolve())
    else:
        parser.error("Specify --observations and --output")


if __name__ == "__main__":
    main()
