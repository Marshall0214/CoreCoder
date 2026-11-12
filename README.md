<div align="center">

# CoreCoder · Issue Repair & Verification

A coding agent project for reproducible patch generation, sandboxed testing, and reviewable repair evidence.

[中文](README_CN.md) · English · [MIT License](LICENSE)

</div>

This fork extends [he-yufeng/CoreCoder](https://github.com/he-yufeng/CoreCoder), by Yufeng He. The original minimal agent and bilingual source-reading series remain available; this repository adds repair evaluation, task services, execution isolation, and public Issue preparation.

## Start here: CLI/API feedback repair

The `feedback-actions-v2` engine connects initial exploration, code reads, constrained edits and repeated public Docker checks to the same CLI/API execution path. Approval, idempotency, restart recovery, cancellation and downloadable evidence remain part of that path. A public pass delivers a candidate for **human review**, with independent acceptance explicitly unavailable.

With the existing source environment, Linux Docker and the prebuilt `corecoder-test-sandbox:v1` image:

```powershell
python -B -m repairflow demo-feedback --output .tmp/feedback-demo-001
```

Use a fresh output directory. This self-contained synthetic task uses six recorded responses, real tools and Docker; it needs no Ollama, GitHub download or paid API. It checks CLI/API patch agreement, approval recovery and duplicate-execution prevention. See the [feedback service guide](docs/issue-feedback-service.md) for D-drive setup, API usage, execution limits, artifacts and acceptance evidence. This is an engineering demonstration, not a repair-accuracy experiment.

## Current capabilities

[Own-agent local evaluation without token cutoffs](docs/local50-unmetered-20261103.md) completed all 50 known tasks: **21/50 accepted**, 33 candidate patches, 309 local Qwen calls and 937,866 measured tokens. Independent grading and all 50 inference traces were verified. This checkpoint-policy run is separate from the historical DeepSeek results.

[Optional mini-SWE-agent integration](docs/mini-swe-integration.md) reuses its unmodified 2.4.6 loop with local Ollama, restricted Docker, independent grading and Langfuse. The fixed five-task development pilot completed at **0/5**, matching the old loop on that subset; this is an integration result, not a replacement or an upstream benchmark score.

[Optional Harness² integration](docs/harness2-integration.md) uses the pinned upstream Propose–Probe–Compose core with our executor and local Ollama editor. Two guidance files are editable by default; an opt-in three-boolean Context Builder config has separate no-model acceptance. [The first failure review](docs/harness2-review-20261104.md) traces retained undefined symbols and duplicate output. The real development task remains unresolved; all attempts and costs are retained and the **21/50 baseline is unchanged**.

The prepared-Issue CLI now supports [symbol reads and edit recovery (Chinese)](docs/symbol-read-recovery.md), with configurable action/edit limits and mandatory re-reads after anchor or version failures. Scripted acceptance is separate from the historical 47/50 result.

Prepared Issues now have a [complete CLI/API path (Chinese)](docs/issue-service.md): trusted registry, execution approval, restart recovery, read-only dependencies, Docker checks, and artifact downloads. A self-contained scripted demo verifies engineering behavior without model calls. Accuracy optimization is deferred.

An optional [local Langfuse adapter (Chinese)](docs/langfuse-local.md) adds task/model/tool/check spans and deterministic scores, without uploading source or prompts. The self-hosted service is running: [server readback verified two traces and 14 observations, login, and persistence across a stack restart](docs/langfuse-server-20261029.md), with zero model calls. See [integration status](docs/advanced-capabilities.md) for Harness² and remaining plans.

[Subsequent native usage acceptance](docs/langfuse-token-usage-20261030.md) verified 1,027 tokens from one local Qwen3.5 27B call across Ollama, local events and Langfuse, with thinking disabled. Missing counters, measured zero, budget estimates and cloud API fees are distinct; scripted responses use ordinary spans.

[Langfuse operations drills](docs/langfuse-operations-20261030.md) add no-model diagnostics and scoped Web/Worker fault drills: local delivery survives telemetry downtime, and queued records become readable after Worker recovery. All services were restored; offline tasks are not automatically backfilled.

[The first SWE-bench Verified Mini task](docs/swebench-mini-20261030.md) now has official grading and two Langfuse dataset control experiments: unchanged code passes 0/2 target tests, the reference patch passes 2/2, and both preserve 77/77 regression tests. No model inference or new Agent accuracy claim is involved.

[The first actual local Agent attempt](docs/swebench-agent-20261030.md) explored that pinned repository with six Qwen calls and 19,364 tokens, thinking disabled. It stopped on repeated reads without a patch: official target tests 0/2, regression tests 77/77. Actual inference and subsequent grading are linked in Langfuse; the failed attempt is retained.

[Mini-50 batch evaluation](docs/swebench-mini-batch.md) runs all 25 Django and 25 Sphinx tasks serially, with fixed local-model settings, per-task harness admission, independent grading, resumable artifacts and a unified Langfuse experiment. A running batch is not a completed accuracy result.

| Area | Implemented | Boundary |
| --- | --- | --- |
| Public GitHub Issues | Read-only import, pinned source, candidate patches and Docker reproduction/preservation checks | CLI with trusted configuration; public-test success requires manual review |
| Repair workflow | Legacy bundle evaluation; optional `feedback-actions-v2` read/edit/public-check loop through CLI/API | Specified Python repositories; public Issue checks end in human review, independent grading stays separate |
| Execution sandbox | Offline, non-root Docker containers with readonly inputs and CPU/memory/PID/time/output limits | Unified repairflow checks; original Bash and legacy evals are not migrated |
| Local service | FastAPI, idempotency, SSE, cancellation, SQLite, LangGraph approval/restart recovery | One local service owner; no multi-user production claim |
| Tools and evidence | Read-only code knowledge MCP; patches, traces, usage, input hashes and reports | No automatic GitHub publishing |

Two entry points currently coexist:

```text
Public Issue + trusted configuration → fixed source → sandbox admission → candidate → public checks → review
Trusted repair bundle → retrieval → candidate patch → feedback → independent checks → report
```

`ready_for_repair` means the original defect was reproduced and declared preservation checks passed. Use the [prepared-Issue CLI](docs/prepared-issue-repair.md) or the `issue-approval-v1` HTTP workflow to generate a candidate. Public-check success ends in `ready_for_review`, never independent acceptance.

## Validation evidence

- **Known-task repair experiment:** 5 Python repositories, 50 upstream-derived defects. With fixed DeepSeek high-reasoning mode, budget and grading, acceptance increased from **43/50 to 47/50 (86% → 94%)**, with **9.38% fewer tokens**. This is a single run on a known task pool, not unseen-Issue or SWE-bench performance. [Report](docs/coverage-full-repair-v1-results.md).
- **Real sandbox acceptance:** 9 Docker cases covering readonly inputs, blocked network, credentials, resource limits, cancellation and recovery; CLI/API historical replay produced identical patches. [Evidence](docs/sandbox-acceptance-20261019.md).
- **Issue preparation:** [Click #3887](https://github.com/pallets/click/issues/3887), pinned to 8.1.8: one expected reproduction failure and three passing preservation tests. No candidate patch or model call. **197 related regression tests passed** before this upstream sync, including 34 Issue-preparation tests and 9 Docker tests. [Guide and evidence](docs/github-issue-preparation.md).
- **Upstream integration:** full local regression **1,667 passed, 3 skipped**, including 9 real Docker tests, with no model inference. [Integration results and skip reasons](docs/upstream-sync-20261019.md).

Historical replay is not fresh model inference. Test success is limited to the declared checks; container isolation does not prevent all grading manipulation inside the same interpreter.

The [43/50 → 47/50 evidence and interview guide (Chinese)](docs/repair50-evidence.md) bundles configurations, code changes, scoring rules, failures, costs, original reports and an offline audit with per-task CSV. The paired result is five gains and one loss. Both rounds already allowed one feedback correction; historical grading predates the Docker sandbox.

The prepared-Issue repair CLI has **200 related regression tests passing**, including two new real Docker cases for delivery and rollback. Acceptance used scripted responses with zero model calls, not a new repair-rate experiment. [Guide](docs/prepared-issue-repair.md).

One subsequent real local run on Click #3887 used Qwen3.5 27B with thinking disabled: two model calls, 8,274 tokens, about 83 seconds. The target remained unfixed; validation rejected the candidates and the final patch was empty. This is a single development case, not a new success-rate result. [Run and failure analysis](docs/local-issue-repair-20261019.md).

A second development run tested module imports and helper context under the same limits. Both generated anchors were rejected; total usage rose to 8,877 tokens. The strategy stays explicitly opt-in, baseline remains the default, and final related regression is **213 passed**. [Comparison and limits](docs/issue-context-round2-20261019.md).

## Quick start: no model API required

Use a source checkout. The published upstream package does not include these repository-level extensions.

```powershell
git clone https://github.com/Marshall0214/CoreCoder.git
cd CoreCoder
python -m pip install --no-cache-dir -e ".[dev,service,workflow,mcp-server]"
```

With the existing corecoder environment, keep runtime state and temporary files on D:

```powershell
New-Item -ItemType Directory -Force 'D:\project_other\CoreCoder\.tmp' | Out-Null
$env:PYTHONDONTWRITEBYTECODE='1'
$env:CORECODER_LIVE_SMOKE=''
$env:CORECODER_HOME='D:\project_other\CoreCoder\.tmp\corecoder-state'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
$env:RUFF_CACHE_DIR='D:\project_other\CoreCoder\.tmp\ruff-cache'
$env:DOCKER_CONTEXT='desktop-linux'
```

Start Docker Desktop with Linux containers and verify its disk data is on D before building. [Sandbox setup](docs/execution-sandbox.md).

```powershell
docker build -f deploy/sandbox/Dockerfile -t corecoder-test-sandbox:v1 deploy/sandbox
$env:CORECODER_RUN_DOCKER_TESTS='1'
python -B -m pytest tests/test_github_issue.py tests/test_sandbox_docker.py -q -p no:cacheprovider
python -B -m repairflow import-issue --url https://github.com/pallets/click/issues/3887 --config configs/issue-tasks/click-3887.json --output .tmp/github-issues/click-3887
```

The import makes public GitHub GET requests. It never executes commands from the Issue, installs repository dependencies, or calls a model. Use a new output directory on each run. It retains `issue.json`, fixed source, trusted checks, admission logs, `task.json`, and `report.json`.

## Repair and approval service

The [shared workflow guide](docs/unified-repair-flow.md) covers trusted-bundle export, exact historical replay, and approval API operation. Historical replay requires previously retained experiment assets; it is not a fresh-clone prerequisite for the self-contained tests above.

```powershell
python -B -m service --port 8004 --timeout 1200 --output .tmp/repair-service
```

Use `CORECODER_REPAIR_BUNDLES` for legacy trusted bundles, or `CORECODER_ISSUE_TASKS` for prepared Issues. Administrators import and register tasks through the CLI; HTTP clients submit catalog IDs. Offline demonstrations use scripted responses; Issue live mode uses local Ollama with thinking disabled.

`CORECODER_HOME` relocates checkpoints, grants, sessions, history, hooks, MCP configuration and pricing overrides. Without it the original upstream home-directory locations are retained. Service workers use task-local state. The ordinary agent's Bash tool remains separate from the Docker verification sandbox.

## Code and documentation

| Path | Purpose |
| --- | --- |
| `corecoder/` | Upstream-based agent engine, tools, providers, sessions and MCP client |
| `repairflow/`, `configs/issue-tasks/` | Shared repair execution and trusted Issue admission |
| `sandbox/`, `deploy/sandbox/` | Container policies and lifecycle |
| `service/`, `workflows/`, `mcp_servers/` | Task API, approval checkpoints and read-only code tools |
| `evals/`, `docs/experiments/` | Evaluation harness, task assets and versioned experiments |

Start with [Issue preparation](docs/github-issue-preparation.md), [repair workflow](docs/unified-repair-flow.md), [sandbox](docs/execution-sandbox.md), and [plan](plan.md). See [upstream sync notes](docs/upstream-sync-20261019.md) for the integration boundary.

For the original agent walkthrough, read the [English source-reading series](article/00-index_EN.md) or [Chinese series](article/00-index.md). Original author attribution and the MIT license are retained.

Core package size only: **30 files, 3,117 physical lines, 2,537 net**; `engine-1462_LoC`. These counts exclude repairflow, sandbox, service and evaluation extensions. Core package version follows upstream **0.8.0**; that is not a versioned release of the complete repair system.
