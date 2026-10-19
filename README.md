<div align="center">

# CoreCoder · Issue Repair & Verification

A coding agent project for reproducible patch generation, sandboxed testing, and reviewable repair evidence.

[中文](README_CN.md) · English · [MIT License](LICENSE)

</div>

This fork extends [he-yufeng/CoreCoder](https://github.com/he-yufeng/CoreCoder), by Yufeng He. The original minimal agent and bilingual source-reading series remain available; this repository adds repair evaluation, task services, execution isolation, and public Issue preparation.

## Current capabilities

| Area | Implemented | Boundary |
| --- | --- | --- |
| Public GitHub Issues | Read-only import, pinned source, candidate patches and Docker reproduction/preservation checks | CLI with trusted configuration; public-test success requires manual review |
| Repair workflow | Target/symbol retrieval, constrained patches, one public-feedback correction, rollback, independent grading | Trusted task bundles and specified Python repositories |
| Execution sandbox | Offline, non-root Docker containers with readonly inputs and CPU/memory/PID/time/output limits | Unified repairflow checks; original Bash and legacy evals are not migrated |
| Local service | FastAPI, idempotency, SSE, cancellation, SQLite, LangGraph approval/restart recovery | One local service owner; no multi-user production claim |
| Tools and evidence | Read-only code knowledge MCP; patches, traces, usage, input hashes and reports | No automatic GitHub publishing |

Two entry points currently coexist:

```text
Public Issue + trusted configuration → fixed source → sandbox admission → candidate → public checks → review
Trusted repair bundle → retrieval → candidate patch → feedback → independent checks → report
```

`ready_for_repair` means the original defect was reproduced and declared preservation checks passed. Run the separate [prepared-Issue repair CLI](docs/prepared-issue-repair.md) to generate and validate a candidate. Without independent grading it produces a reviewable patch, never an independent acceptance claim. New-task HTTP approval remains a future milestone.

## Validation evidence

- **Known-task repair experiment:** 5 Python repositories, 50 upstream-derived defects. With fixed DeepSeek high-reasoning mode, budget and grading, acceptance increased from **43/50 to 47/50 (86% → 94%)**, with **9.38% fewer tokens**. This is a single run on a known task pool, not unseen-Issue or SWE-bench performance. [Report](docs/coverage-full-repair-v1-results.md).
- **Real sandbox acceptance:** 9 Docker cases covering readonly inputs, blocked network, credentials, resource limits, cancellation and recovery; CLI/API historical replay produced identical patches. [Evidence](docs/sandbox-acceptance-20261019.md).
- **Issue preparation:** [Click #3887](https://github.com/pallets/click/issues/3887), pinned to 8.1.8: one expected reproduction failure and three passing preservation tests. No candidate patch or model call. **197 related regression tests passed** before this upstream sync, including 34 Issue-preparation tests and 9 Docker tests. [Guide and evidence](docs/github-issue-preparation.md).
- **Upstream integration:** full local regression **1,667 passed, 3 skipped**, including 9 real Docker tests, with no model inference. [Integration results and skip reasons](docs/upstream-sync-20261019.md).

Historical replay is not fresh model inference. Test success is limited to the declared checks; container isolation does not prevent all grading manipulation inside the same interpreter.

The prepared-Issue repair CLI has **200 related regression tests passing**, including two new real Docker cases for delivery and rollback. Acceptance used scripted responses with zero model calls, not a new repair-rate experiment. [Guide](docs/prepared-issue-repair.md).

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

Set `CORECODER_REPAIR_BUNDLES` to an administrator-controlled task registry when using the approval repair endpoint. Approval is required before execution; GitHub Issue import is currently a separate CLI entry point. Model-backed repair is not part of the default quick start. New model trials should keep thinking off unless explicitly enabled, and should not be combined with historical high-reasoning results.

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
