"""Parent-owned workspaces, grading and artifacts for controlled repair tasks."""

import difflib
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .process import run_process, run_tests
from .runtime import Events
from .schema import RunConfig, Task, relative_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUITE = Path(__file__).resolve().parent / "fixtures"


def implementation_metadata() -> dict:
    files = {}
    for folder in ("corecoder", "evals"):
        for path in (PROJECT_ROOT / folder).rglob("*.py"):
            if "fixtures" not in path.parts and "__pycache__" not in path.parts:
                files[path.relative_to(PROJECT_ROOT).as_posix()] = path.read_bytes()
    versions = {}
    for name in ("openai", "rich", "python-dotenv"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    git = {}
    for name, args in (("commit", ["rev-parse", "HEAD"]), ("status", ["status", "--porcelain"])):
        try:
            result = subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=5, check=False)
            git[name] = result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            git[name] = None
    return {"source_hash": digest(files), "dependencies": versions, "git": git}


def snapshot(root: Path) -> dict[str, bytes]:
    result = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if any(part in {"__pycache__", ".eval-logs"} for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            result[name] = b"[symlink]"
        elif path.is_file():
            if path.stat().st_size > 1_000_000:
                raise ValueError(f"Fixture output file too large: {name}")
            result[name] = path.read_bytes()
    return result


def digest(files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for name, content in sorted(files.items()):
        h.update(name.encode() + b"\0" + content + b"\0")
    return h.hexdigest()


def changes(before: dict[str, bytes], after: dict[str, bytes]) -> tuple[list[str], str]:
    changed = [name for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)]
    patch = []
    for name in changed:
        patch.extend(difflib.unified_diff(
            before.get(name, b"").decode("utf-8", errors="replace").splitlines(keepends=True),
            after.get(name, b"").decode("utf-8", errors="replace").splitlines(keepends=True),
            fromfile=f"a/{name}" if name in before else "/dev/null",
            tofile=f"b/{name}" if name in after else "/dev/null"))
    return changed, "".join(patch)


def reference_edits(task: Task) -> list[dict]:
    edits = json.loads((task.root / "reference.json").read_text(encoding="utf-8"))
    for edit in edits:
        if relative_path(edit["file"]) not in task.allowed_files or not edit["old"]:
            raise ValueError("Reference edit outside allowed source files")
    return edits


def verify(task: Task, workspace: Path, run_root: Path, before: dict[str, bytes], timeout: int) -> dict:
    after = snapshot(workspace)
    changed, patch = changes(before, after)
    (run_root / "patch.diff").write_text(patch, encoding="utf-8")
    violations = [name for name in changed if name not in task.allowed_files]
    violations.extend(name for name in task.allowed_files
                      if not (workspace / name).is_file() or (workspace / name).is_symlink())
    if violations:
        return {"passed": False, "changed_files": changed, "scope_violations": sorted(set(violations)),
                "target": None, "regression": None}
    # Grade a fresh copy. Never trust tests or verifier files from the candidate workspace.
    grading = run_root / "grading"
    shutil.copytree(task.root / "workspace", grading)
    for name in task.allowed_files:
        (grading / name).write_bytes(after[name])
    shutil.copytree(task.root / "hidden_tests", grading / "_target_tests")
    target = run_tests(grading, "_target_tests", timeout, run_root, "target")
    regression = run_tests(grading, "tests", timeout, run_root, "regression")
    return {"passed": target["passed"] and regression["passed"], "changed_files": changed,
            "scope_violations": [], "target": target, "regression": regression}


def run_task(task: Task, config: RunConfig, output: Path, repetition: int = 1) -> dict:
    output = output.resolve()
    if output.is_relative_to(task.root):
        raise ValueError("Output directory cannot be inside task fixtures")
    run_id = f"{task.task_id}-{repetition}-{uuid.uuid4().hex[:10]}"
    run_root = output / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    events = Events(run_root / "trace.jsonl", run_id)
    report = {"schema_version": 1, "run_id": run_id, "task_id": task.task_id, "source": "synthetic",
              "repetition": repetition, "mode": config.mode, "benchmark_eligible": config.mode == "live",
              "config": config.to_dict(), "status": "infrastructure_error", "accepted": False,
              "python": platform.python_version(), "platform": platform.platform(), "metrics": None,
              "verification": None, "artifacts": str(run_root)}
    started = time.perf_counter()
    try:
        workspace = run_root / "workspace"
        shutil.copytree(task.root / "workspace", workspace)
        before = snapshot(workspace)
        report["fixture_hash"] = digest(before)
        report["implementation"] = implementation_metadata()
        report["grader_hash"] = digest(snapshot(task.root / "hidden_tests"))
        report["manifest_hash"] = hashlib.sha256((task.root / "task.json").read_bytes()).hexdigest()
        report["worker_seconds"] = 0.0
        events.emit("task_started", task_id=task.task_id, mode=config.mode)
        if config.mode == "reference":
            for edit in reference_edits(task):
                path = workspace / edit["file"]
                text = path.read_text(encoding="utf-8")
                if text.count(edit["old"]) != 1:
                    raise ValueError("Reference edit is not unique")
                path.write_text(text.replace(edit["old"], edit["new"]), encoding="utf-8")
            worker = {"status": "completed", "metrics": None}
        elif config.mode == "unchanged":
            worker = {"status": "completed", "metrics": None}
        else:
            job = {"run_id": run_id, "workspace": str(workspace), "description": task.description,
                   "allowed_files": list(task.allowed_files), "config": config.to_dict()}
            if config.mode == "scripted":
                job["oracle_edits"] = reference_edits(task)
            job_path = run_root / "job.json"
            job_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
            env = dict(os.environ)
            env["PYTHONPATH"] = str(PROJECT_ROOT)
            env["PYTHONNOUSERSITE"] = "1"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            result = run_process([sys.executable, "-m", "evals.worker", str(job_path)], workspace,
                                 config.wall_timeout, run_root / "worker.stdout.txt", run_root / "worker.stderr.txt", env)
            report["worker_seconds"] = result["seconds"]
            result_path = run_root / "worker-result.json"
            if result["timed_out"]:
                worker = {"status": "timeout", "metrics": None}
            elif result["returncode"] != 0 or not result_path.exists():
                worker = {"status": "agent_error", "metrics": None, "error": "Worker failed; see worker.stderr.txt"}
            else:
                worker = json.loads(result_path.read_text(encoding="utf-8"))
        report["worker"] = worker
        report["metrics"] = worker.get("metrics")
        verification = verify(task, workspace, run_root, before, config.test_timeout)
        report["verification"] = verification
        report["accepted"] = worker["status"] == "completed" and verification["passed"]
        report["status"] = "passed" if report["accepted"] else (
            "failed_verification" if worker["status"] == "completed" else worker["status"])
    except KeyboardInterrupt:
        report["status"] = "cancelled"
    except Exception as exc:  # noqa: BLE001 - every run must preserve an error report
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        report["seconds"] = round(time.perf_counter() - started, 4)
        events.emit("task_finished", status=report["status"], accepted=report["accepted"])
        records = []
        report["trace_invalid_lines"] = 0
        for line in events.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                report["trace_invalid_lines"] += 1
        report["tool_calls"] = sum(record["event"] == "tool_started" for record in records)
        report["tool_seconds"] = round(sum(record.get("seconds", 0) for record in records
                                           if record["event"] == "tool_finished"), 4)
        report = events.clean(report)
        (run_root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def write_summary(reports: list[dict], output: Path) -> Path:
    path = output / f"summary-{uuid.uuid4().hex[:10]}"
    summary = {"runs": len(reports), "accepted": sum(r["accepted"] for r in reports),
               "benchmark_eligible": all(r["benchmark_eligible"] for r in reports), "reports": reports}
    path.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Repair evaluation", "", f"Accepted: {summary['accepted']}/{summary['runs']}",
             f"Model benchmark eligible: {summary['benchmark_eligible']}", "",
             "| Task | Mode | Status | Target | Regression | Seconds |", "| --- | --- | --- | --- | --- | --- |"]
    for report in reports:
        verification = report.get("verification") or {}
        target = (verification.get("target") or {}).get("passed", "unknown")
        regression = (verification.get("regression") or {}).get("passed", "unknown")
        lines.append(f"| {report['task_id']} | {report['mode']} | {report['status']} | {target} | {regression} | {report['seconds']} |")
    path.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path.with_suffix(".md")
