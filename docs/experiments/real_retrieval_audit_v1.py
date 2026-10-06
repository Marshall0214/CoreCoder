"""Public-only Click retrieval and packing audit; upstream labels load after retrieval."""

import argparse
import difflib
import hashlib
import json
import time
from pathlib import Path
from statistics import mean

from corecoder.retrieval.keyword import KeywordIndex
from docs.experiments.dependency_context_v1 import expand
from docs.experiments.vector_repair_v1 import ENGINE, pack
from docs.experiments.vector_retrieval_v1 import OllamaEmbeddings, VectorIndex
from evals.retrieval_eval import coverage, file_ranking
from evals.runner import digest, implementation_metadata, snapshot
from evals.schema import relative_path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "evals/real_defects/staged-suite-v1.json"
MANIFEST_SHA = "f04e7eee5be75ef89dccbedae38759eb38042bbe8b4c1d6f553823031831ba96"
EMBED_DIGEST = "ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d"
STRATEGIES = ("bm25", "dense", "hybrid")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_cases(admissions):
    """Project admission/catalog metadata into public fields, without opening after/checks."""
    if sha(MANIFEST) != MANIFEST_SHA or implementation_metadata()["source_hash"] != ENGINE:
        raise ValueError("Frozen development manifest or engine changed")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if set(admissions) != {s["name"] for s in manifest["sources"]}:
        raise ValueError("Supply exactly the original/crossfile/expansion admissions")
    result = []
    for source in manifest["sources"]:
        catalog = MANIFEST.parent / relative_path(source["catalog"])
        if sha(catalog) != source["catalog_sha256"]:
            raise ValueError("Frozen catalog changed")
        admission_path = admissions[source["name"]].resolve()
        admission = json.loads(admission_path.read_text(encoding="utf-8"))
        if admission["catalog_hash"] != sha(catalog):
            raise ValueError("Admission catalog mismatch")
        catalog_cases = json.loads(catalog.read_text(encoding="utf-8"))["cases"]
        if [r["case_id"] for r in catalog_cases] != source["tasks"]:
            raise ValueError("Frozen task order changed")
        for item in catalog_cases:
            task_id = relative_path(item["case_id"])
            rows = [r for r in admission["cases"] if r["case_id"] == task_id]
            if len(rows) != 1 or not rows[0]["admitted"]:
                raise ValueError("Task needs successful recorded admission")
            before = admission_path.parent / task_id / "before"
            before_hash = rows[0]["revisions"]["before"]["tree_hash"]
            files = snapshot(before)
            if digest(files) != before_hash:
                raise ValueError("Admitted before snapshot changed")
            allowed = sorted(name for name in files if name.startswith("src/click/") and name.endswith(".py"))
            if not allowed:
                raise ValueError("Missing public Click package")
            result.append({"task_id": task_id, "description": item["public_problem"],
                           "repo": item["repo"], "before_commit": item["before_commit"],
                           "before": before, "before_hash": before_hash, "allowed_files": allowed,
                           "admission_path": admission_path, "admission_sha256": sha(admission_path),
                           "catalog": catalog, "catalog_sha256": sha(catalog)})
    if len(result) != 7 or len({c["task_id"] for c in result}) != 7:
        raise ValueError("Expected exactly seven admitted development cases")
    return result


def bounded_chunks(ranked, max_chars=6000, top_k=5):
    """Feasibility probe: retain full original chunks, never truncate or add source."""
    selected, discarded, chars = [], [], 0
    for rank, (score, chunk) in enumerate(ranked, 1):
        if len(selected) == top_k:
            break
        if chars + len(chunk.content) > max_chars:
            discarded.append({"path": chunk.path, "start_line": chunk.start_line,
                              "rank": rank, "reason": "full_chunk_budget", "chars": len(chunk.content)})
            continue
        selected.append({"path": chunk.path, "start_line": chunk.start_line, "end_line": chunk.end_line,
                         "content_hash": chunk.content_hash, "content": chunk.content,
                         "rank": rank, "score": score})
        chars += len(chunk.content)
    return {"selected": selected, "discarded": discarded, "evidence_chars": chars,
            "max_chars": max_chars, "max_chunks": top_k}


def observe(case, provider):
    workspace, allowed = case["before"], case["allowed_files"]
    query = case["description"] + " contract contracts"
    index = KeywordIndex(workspace, allowed)
    metadata = index.refresh()
    dense = VectorIndex(workspace, provider, allowed, "dense")
    usage_before = dict(provider.usage)
    started = time.perf_counter()
    if dense.refresh()["index_hash"] != metadata["index_hash"]:
        raise ValueError("Retrievers indexed different corpora")
    ranks = {"bm25": index.rank(query), "dense": dense.rank(query)}
    dense.strategy = "hybrid"
    ranks["hybrid"] = dense.rank(query)
    build_and_rank_seconds = time.perf_counter() - started
    observation = {"task_id": case["task_id"], "query": query, "index": metadata,
                   "rankings": {s: file_ranking(r) for s, r in ranks.items()},
                   "chunk_rankings": {s: [{"path": c.path, "start_line": c.start_line, "end_line": c.end_line,
                                           "content_hash": c.content_hash, "score": score} for score, c in r]
                                      for s, r in ranks.items()}}
    packing = {}
    for strategy, ranked in ranks.items():
        whole, whole_meta = pack(workspace, allowed, observation, strategy)
        dependencies, dependency_meta = expand(workspace, allowed, whole, whole_meta)
        packing[strategy] = {"whole_files": {"selected": whole, "metadata": whole_meta},
                             "whole_files_imports": {"selected": dependencies, "metadata": dependency_meta},
                             "full_chunks": bounded_chunks(ranked)}
    if digest(snapshot(workspace)) != case["before_hash"]:
        raise ValueError("Public snapshot changed during retrieval")
    observation.update(packing=packing, build_and_rank_seconds=build_and_rank_seconds,
                       embedding_usage_delta={key: provider.usage[key] - value for key, value in usage_before.items()})
    return observation


def labels(case):
    """Parent-only scoring; never provide after source or changed-file labels to a retriever."""
    if sha(case["catalog"]) != case["catalog_sha256"] or sha(case["admission_path"]) != case["admission_sha256"]:
        raise ValueError("Scoring provenance changed")
    catalog = json.loads(case["catalog"].read_text(encoding="utf-8"))["cases"]
    source = next(c for c in catalog if c["case_id"] == case["task_id"])
    admission = json.loads(case["admission_path"].read_text(encoding="utf-8"))
    row = next(r for r in admission["cases"] if r["case_id"] == case["task_id"])
    after = case["before"].parent / "after"
    before_files, after_files = snapshot(case["before"]), snapshot(after)
    if digest(before_files) != case["before_hash"] or digest(after_files) != row["revisions"]["after"]["tree_hash"]:
        raise ValueError("Scoring snapshot changed")
    actual = sorted(name for name in case["allowed_files"] if before_files[name] != after_files.get(name))
    if actual != sorted(source["changed_source_files"]):
        raise ValueError("Source repair labels differ from admitted catalog")
    spans = []
    for name in actual:
        before = before_files[name].decode("utf-8").splitlines()
        fixed = after_files[name].decode("utf-8").splitlines()
        for op, i, j, _, _ in difflib.SequenceMatcher(None, before, fixed, autojunk=False).get_opcodes():
            if op == "equal":
                continue
            # Insertions have no removed lines: use one adjacent before-line anchor.
            start, end = (i + 1, j) if j > i else (max(1, min(i + 1, len(before))), max(1, min(i + 1, len(before))))
            spans.append({"path": name, "start_line": start, "end_line": end, "operation": op})
    return actual, spans


def span_recall(selected, spans):
    expected = {(r["path"], line) for r in spans for line in range(r["start_line"], r["end_line"] + 1)}
    if not expected:
        raise ValueError("No upstream repair spans")
    covered = {(r["path"], line) for r in selected for line in range(r["start_line"], r["end_line"] + 1)}
    return len(expected & covered) / len(expected)


def evaluate(cases, output, provider):
    if output.exists() or any(output.resolve().is_relative_to(c["before"].parent.resolve()) for c in cases):
        raise ValueError("Use fresh output outside admitted snapshots")
    if provider.model_digest != EMBED_DIGEST:
        raise ValueError("Embedding model differs from frozen multilingual baseline")
    output.mkdir(parents=True, exist_ok=False)
    inputs = [{k: str(v) if isinstance(v, Path) else v for k, v in c.items()} for c in cases]
    protocol = {"protocol": "real-retrieval-audit-v1", "development_only": True, "benchmark_eligible": False,
                "manifest_sha256": MANIFEST_SHA, "engine_hash": ENGINE, "embedding_model": provider.model,
                "embedding_digest": provider.model_digest, "chunk_lines": 40, "budget_chars": 6000,
                "whole_file_top_k": 5, "full_chunk_max_k": 5, "dependency_depth": 2,
                "query": "public_problem + literal contract contracts; no strategy-specific rewrite",
                "inputs": inputs, "adapter_sha256": sha(Path(__file__))}
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    observations = []
    for case in cases:
        observations.append(observe(case, provider))
        (output / "observations.json").write_text(json.dumps(observations, indent=2), encoding="utf-8")
        print(case["task_id"] + ": public retrieval frozen", flush=True)
    provider.verify_identity()
    observation_sha = sha(output / "observations.json")
    # All queries, corpus retrieval and budget decisions are fixed on disk before labels load.
    rows = []
    for case, observation in zip(cases, observations):
        targets, spans = labels(case)
        scores = {}
        for strategy in STRATEGIES:
            policy = observation["packing"][strategy]
            scores[strategy] = {"file_recall_at_5": coverage(observation["rankings"][strategy][:5], targets)["recall"],
                                "whole_file_recall": coverage([r["path"] for r in policy["whole_files"]["selected"]], targets)["recall"],
                                "dependency_file_recall": coverage([r["path"] for r in policy["whole_files_imports"]["selected"]], targets)["recall"],
                                "chunk_file_recall": coverage([r["path"] for r in policy["full_chunks"]["selected"]], targets)["recall"],
                                "chunk_changed_line_recall": span_recall(policy["full_chunks"]["selected"], spans)}
        rows.append({"task_id": case["task_id"], "targets": targets, "before_spans": spans, "scores": scores})
    summary = {s: {metric: mean(r["scores"][s][metric] for r in rows)
                   for metric in rows[0]["scores"][s]} for s in STRATEGIES}
    report = {"protocol": protocol, "complete": True, "repair_llm_calls": 0,
              "observations_sha256": observation_sha, "embedding_usage": provider.usage,
              "dimension": provider.dimension, "summary": summary, "rows": rows,
              "limitations": "7 development cases from Click only; reference files/spans are incomplete proxies, not repair success; full chunks and whole files use different K units"}
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission", action="append", required=True, metavar="SOURCE=PATH")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    admissions = {}
    for entry in args.admission:
        name, separator, path = entry.partition("=")
        if not separator or name in admissions or not path:
            parser.error("Supply unique SOURCE=PATH admissions")
        admissions[name] = Path(path)
    cases = public_cases(admissions)
    if args.validate_only:
        for case in cases:
            metadata = KeywordIndex(case["before"], case["allowed_files"]).refresh()
            print(f'{case["task_id"]}: {metadata["files"]} files, {metadata["chunks"]} chunks')
        return
    evaluate(cases, args.output.resolve(), OllamaEmbeddings())


if __name__ == "__main__":
    main()
