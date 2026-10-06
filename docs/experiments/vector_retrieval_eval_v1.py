"""Fixed-query offline comparison; scoring labels are read after retrieval only."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from statistics import mean

from corecoder.retrieval.keyword import KeywordIndex
from docs.experiments.vector_retrieval_v1 import OllamaEmbeddings, VectorIndex, adapter_hash
from evals.retrieval_eval import coverage, file_ranking
from evals.runner import DEFAULT_SUITE, implementation_metadata, reference_edits, snapshot
from evals.schema import load_suite


def evaluate(suites, output, provider):
    tasks = [task for suite in suites for task in load_suite(suite)]
    if len({t.task_id for t in tasks}) != len(tasks):
        raise ValueError("Duplicate task IDs")
    if any(output.resolve().is_relative_to(t.root.resolve()) for t in tasks):
        raise ValueError("Output must be outside fixtures")
    output.mkdir(parents=True, exist_ok=False)
    observations = []
    for task in tasks:
        workspace = task.root / "workspace"
        before = snapshot(workspace)
        query = task.description + " contract contracts"
        lexical = KeywordIndex(workspace, task.allowed_files)
        metadata = lexical.refresh()
        dense = VectorIndex(workspace, provider, task.allowed_files, "dense")
        build_started = time.perf_counter()
        usage_before = dict(provider.usage)
        if dense.refresh()["index_hash"] != metadata["index_hash"]:
            raise ValueError("Corpus mismatch")
        build_seconds = time.perf_counter() - build_started
        started = time.perf_counter()
        dense_rows = dense.rank(query)
        dense_seconds = time.perf_counter() - started
        started = time.perf_counter()
        lexical_rows = lexical.rank(query)
        bm25_seconds = time.perf_counter() - started
        dense.strategy = "hybrid"
        started = time.perf_counter()
        hybrid_rows = dense.rank(query)
        hybrid_seconds = time.perf_counter() - started
        if snapshot(workspace) != before:
            raise ValueError("Workspace changed during retrieval")
        row = {"task_id": task.task_id, "query": query, "index": metadata,
               "rankings": {"bm25": file_ranking(lexical_rows), "dense": file_ranking(dense_rows),
                            "hybrid": file_ranking(hybrid_rows)},
               "chunk_rankings": {name: [{"path": c.path, "start_line": c.start_line,
                                          "end_line": c.end_line, "content_hash": c.content_hash,
                                          "score": score} for score, c in rows]
                                  for name, rows in (("bm25", lexical_rows), ("dense", dense_rows),
                                                     ("hybrid", hybrid_rows))},
               "rank_seconds": {"bm25": bm25_seconds, "dense_with_query_embedding": dense_seconds,
                                "hybrid_with_cached_embeddings": hybrid_seconds},
               "vector_build_seconds": build_seconds,
               "embedding_usage_delta": {key: provider.usage[key] - value
                                         for key, value in usage_before.items()}}
        observations.append(row)
        print(task.task_id + ": retrieved", flush=True)
    # Persist all observations before opening any reference-edit labels.
    observation_bytes = json.dumps(observations, ensure_ascii=False, indent=2).encode()
    (output / "observations.json").write_bytes(observation_bytes)
    for task, row in zip(tasks, observations):
        targets = sorted({edit["file"] for edit in reference_edits(task)})
        row["targets"] = targets
        row["scores"] = {name: {str(k): coverage(ranking[:k], targets)["recall"]
                                for k in (1, 3, 5, 10)} for name, ranking in row["rankings"].items()}
    provider.verify_identity()
    report = {"protocol": "vector-retrieval-v1", "tasks": len(tasks), "chunk_lines": 40,
              "query_policy": "description + literal contract contracts; no backend-specific rewrite",
              "top_k_unit": "unique files; complete chunk rankings also retained", "rrf_constant": 60,
              "label_limitation": "Reference-edited source files are incomplete relevance proxies, not repair success",
              "model": provider.model, "model_digest": provider.model_digest,
              "dimension": provider.dimension, "embedding_usage": provider.usage,
              "engine_hash": implementation_metadata()["source_hash"], "adapter_hash": adapter_hash(),
              "evaluator_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "observations_sha256": hashlib.sha256(observation_bytes).hexdigest(),
              "mean_file_recall": {name: {str(k): mean(r["scores"][name][str(k)] for r in observations)
                                          for k in (1, 3, 5, 10)} for name in ("bm25", "dense", "hybrid")},
              "rows": observations}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["mean_file_recall"], indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suite", type=Path, action="append")
    parser.add_argument("--model", default="qwen3-embedding:0.6b")
    args = parser.parse_args()
    evaluate(args.suite or [DEFAULT_SUITE, DEFAULT_SUITE / "localization-v1",
                           DEFAULT_SUITE / "retrieval-overlap-v1"],
             args.output, OllamaEmbeddings(args.model))


if __name__ == "__main__":
    main()
