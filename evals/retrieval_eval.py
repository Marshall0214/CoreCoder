"""Offline file-level retrieval evaluation; reference edits are scoring proxies only."""

import argparse
import hashlib
import json
import uuid
from dataclasses import replace
from pathlib import Path
from statistics import mean

from corecoder.retrieval.keyword import KeywordIndex

from .pipeline import bounded_evidence, local_imports
from .runner import DEFAULT_SUITE, digest, implementation_metadata, reference_edits, snapshot
from .runtime import Events
from .schema import RunConfig, load_suite


def file_ranking(ranked):
    """First chunk occurrence defines a unique file's rank, as in the pipeline."""
    return list(dict.fromkeys(chunk.path for _, chunk in ranked))


def coverage(paths, targets):
    targets = set(targets)
    if not targets:
        raise ValueError("Scoring targets must be nonempty")
    hits = sorted(set(paths) & targets)
    return {"hits": hits, "missing": sorted(targets - set(hits)), "recall": len(hits) / len(targets)}


def dependency_closure(workspace, seeds, allowed_files, indexed_files, max_depth):
    """Diagnostic closure without packing limits; not the actual request evidence."""
    queue = [(name, 0) for name in seeds]
    visited, files = set(), []
    for name, depth in queue:
        if name in visited or name not in indexed_files:
            continue
        visited.add(name)
        path = workspace / name
        if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("Dependency path escaped workspace")
        files.append(name)
        if name.endswith(".py") and depth < max_depth:
            queue.extend((dep, depth + 1) for dep in local_imports(name, path.read_bytes().decode("utf-8"), allowed_files))
    return files


def collect(task, config, trace_path):
    """No reference files or labels are read by retrieval or evidence construction."""
    workspace = task.root / "workspace"
    events = Events(trace_path, f"{task.task_id}-k{config.evidence_top_k}")
    evidence = bounded_evidence(workspace, task.description, task.allowed_files, config, events)
    selection = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[-1])
    index = KeywordIndex(workspace, task.allowed_files)
    metadata = index.refresh()
    if metadata["index_hash"] != selection["index"]["index_hash"]:
        raise ValueError("Index changed during offline evaluation")
    ranking = file_ranking(index.rank(selection["query"]))
    seeds = [item["path"] for item in selection["seeds"]]
    if seeds != ranking[:config.evidence_top_k]:
        raise ValueError("Offline ranking differs from pipeline selection")
    expanded = dependency_closure(workspace, seeds, task.allowed_files,
                                  {chunk.path for chunk in index.chunks}, config.evidence_dependency_depth)
    return {"query": selection["query"], "ranking": ranking, "seeds": seeds,
            "dependency_closure": expanded, "selected": [item["path"] for item in evidence],
            "evidence_manifest": [{key: value for key, value in item.items() if key != "content"} for item in evidence],
            "selection": selection}


def score(observation, targets):
    ranking = observation["ranking"]
    first = next((rank for rank, name in enumerate(ranking, 1) if name in targets), None)
    return {"seed": coverage(observation["seeds"], targets),
            "expanded": coverage(observation["dependency_closure"], targets),
            "selected": coverage(observation["selected"], targets),
            "reciprocal_rank": 1 / first if first else 0.0,
            "first_target_rank": first}


def evaluate(suites, widths, output, config):
    tasks = [(str(suite.resolve()), task) for suite in suites for task in load_suite(suite)]
    if len({task.task_id for _, task in tasks}) != len(tasks):
        raise ValueError("Duplicate task IDs across suites")
    if not widths or len(set(widths)) != len(widths):
        raise ValueError("Widths must be nonempty and unique")
    configs = [replace(config, evidence_top_k=width) for width in widths]
    if config.mode != "pipeline" or config.search_backend != "keyword":
        raise ValueError("Offline evaluator requires keyword pipeline config")
    if any(output.resolve().is_relative_to(task.root.resolve()) for _, task in tasks):
        raise ValueError("Output cannot be inside task fixtures")
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for suite, task in tasks:
        before = snapshot(task.root / "workspace")
        observations = [(current, collect(task, current, output / f"{task.task_id}-k{current.evidence_top_k}.jsonl"))
                        for current in configs]
        # Labels are loaded only after every retrieval observation is fixed.
        targets = sorted({edit["file"] for edit in reference_edits(task)})
        if not targets:
            raise ValueError("Reference repair must label at least one source file")
        for current, observation in observations:
            rows.append({"task_id": task.task_id, "suite": suite, "config": current.to_dict(),
                         "targets": targets, "metrics": score(observation, targets), "observation": observation,
                         "fixture_hash": digest(before),
                         "manifest_hash": hashlib.sha256((task.root / "task.json").read_bytes()).hexdigest(),
                         "label_hash": hashlib.sha256((task.root / "reference.json").read_bytes()).hexdigest()})
        if snapshot(task.root / "workspace") != before:
            raise ValueError("Offline retrieval changed a fixture")
    aggregates = []
    for suite in sorted({row["suite"] for row in rows}):
        for width in widths:
            subset = [row for row in rows if row["suite"] == suite and row["config"]["evidence_top_k"] == width]
            aggregates.append({"suite": suite, "top_k": width, "tasks": len(subset),
                               **{f"{stage}_macro_recall": mean(row["metrics"][stage]["recall"] for row in subset)
                                  for stage in ("seed", "expanded", "selected")},
                               "mrr": mean(row["metrics"]["reciprocal_rank"] for row in subset)})
    report = {"protocol": "repair-file-retrieval-v1", "benchmark_eligible": False, "model_calls": 0,
              "label_definition": "unique reference-edited source files; incomplete relevance proxy",
              "implementation": implementation_metadata(), "rows": rows, "aggregates": aggregates}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Offline repair-file retrieval", "", "Labels: reference-edited source files only; no model calls.", "",
             "| Suite | K | Tasks | Seed recall | Expanded recall | Selected recall | MRR |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in aggregates:
        lines.append(f"| {Path(row['suite']).name} | {row['top_k']} | {row['tasks']} | "
                     f"{row['seed_macro_recall']:.3f} | {row['expanded_macro_recall']:.3f} | "
                     f"{row['selected_macro_recall']:.3f} | {row['mrr']:.3f} |")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, action="append")
    parser.add_argument("--top-k", type=int, nargs="+", default=[1, 3, 5, 10])
    parser.add_argument("--max-chars", type=int, default=6000)
    parser.add_argument("--dependency-depth", type=int, default=2)
    parser.add_argument("--output", type=Path, default=Path(".tmp/evals/retrieval-quality-v1"))
    args = parser.parse_args()
    suites = args.suite or [DEFAULT_SUITE, DEFAULT_SUITE / "localization-v1", DEFAULT_SUITE / "retrieval-overlap-v1"]
    try:
        config = RunConfig(mode="pipeline", search_backend="keyword", evidence_order="path",
                           search_max_chars=args.max_chars, evidence_dependency_depth=args.dependency_depth)
        output = args.output.resolve() / uuid.uuid4().hex[:10]
        report = evaluate(suites, args.top_k, output, config)
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    print(f"{len(report['rows'])} observations, {len({row['task_id'] for row in report['rows']})} tasks, 0 model calls")
    print(output / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
