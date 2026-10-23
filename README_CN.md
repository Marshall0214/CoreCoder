<div align="center">

# CoreCoder · Issue 自动修复与验证

围绕代码定位、候选补丁、沙箱验证与结果审查构建的 Coding Agent 工程项目。

中文 · [English](README.md) · [MIT 许可证](LICENSE)

</div>

本仓库扩展自 Yufeng He 的 [he-yufeng/CoreCoder](https://github.com/he-yufeng/CoreCoder)，保留原始最小 Agent 和双语源码导读，新增修复评测、任务服务、执行隔离及真实 Issue 准备能力。

## 当前能力

新 Issue CLI 已接入 [read_symbol 与编辑恢复](docs/symbol-read-recovery.md)：可配置步数和编辑次数，锚点或版本失败后强制重读。新流程的脚本测试不计入历史 47/50。

| 方向 | 已实现 | 使用边界 |
| --- | --- | --- |
| GitHub Issue 流程 | 只读导入、固定版本、候选补丁及 Docker 复现/回归检查 | CLI 与可信配置；公开测试通过后仍需人工审查 |
| 修复闭环 | 目标/符号检索、受约束补丁、最多一次公开反馈修正、失败回滚、独立评分 | 可信任务包与指定 Python 仓库 |
| 执行沙箱 | 禁网、非 root、只读输入，限制 CPU、内存、进程数、时间及日志 | 覆盖统一 repairflow 检查，原始 Bash 和旧 evals 尚未迁移 |
| 本地服务 | FastAPI、幂等提交、SSE、取消、SQLite、LangGraph 审批与重启恢复 | 单服务实例，不宣称多用户生产可用 |
| 工具与证据 | 只读代码知识 MCP，保存补丁、Trace、用量、输入哈希和报告 | 尚不自动向 GitHub 发布 |

当前保留两条入口：

```text
公开 Issue + 可信配置 → 固定源码 → 沙箱复现 → 候选补丁 → 公开测试 → 人工审查
可信修复任务包 → 代码检索 → 候选补丁 → 测试反馈 → 独立验收 → 报告
```

`ready_for_repair` 表示原始问题已复现、约定正常行为检查通过。通过专用 [repair-issue CLI](docs/prepared-issue-repair.md) 才会生成并验证候选；没有独立评分时只交付待审查补丁。新任务 HTTP 审批尚待接入。

## 验证结果

- **已知任务池修复实验：**5 个 Python 仓库、50 项真实来源缺陷。固定 DeepSeek 高思考模式、预算与评分协议，单轮通过数从 **43/50 提升至 47/50（86% → 94%）**，Token 降低 **9.38%**。结果不是陌生 Issue 或 SWE-bench 成绩。[评测报告](docs/coverage-full-repair-v1-results.md)。
- **真实沙箱验收：**9 项 Docker 用例覆盖只读、禁网、密钥隔离、资源限制、取消及重启清理；CLI/API 历史回放补丁一致。[验收证据](docs/sandbox-acceptance-20261019.md)。
- **Issue 准备验收：**[Click #3887](https://github.com/pallets/click/issues/3887)，固定 8.1.8，出现 1 项预期复现失败、3 项正常行为通过，没有生成补丁或调用模型。上游同步前相关回归 **197 项通过**，含 34 项准备测试和 9 项真实 Docker 用例。[使用与证据](docs/github-issue-preparation.md)。
- **上游整合验收：**本地全量回归 **1667 项通过、3 项跳过**，含 9 项真实 Docker 测试，无模型推理。[验收结果及跳过原因](docs/upstream-sync-20261019.md)。

历史回放不计为新模型推理。测试通过仅覆盖约定检查；容器隔离不等同于同解释器评分完全防篡改。

[43/50 → 47/50 证据与面试说明](docs/repair50-evidence.md)集中列出对照配置、代码改动、评分条件、失败及成本，并附可离线核算的原始报告和逐任务 CSV。实际为新增成功 5 项、丢失 1 项；两轮都已有最多一次反馈修正，历史评分未使用后来加入的 Docker 沙箱。

准备任务修复 CLI 已通过 **200 项相关回归**，含新增的两项真实 Docker 交付/回滚用例。验收仅使用脚本响应、模型调用为零，不构成新的修复率实验。[使用说明](docs/prepared-issue-repair.md)。

随后补充一次 Click #3887 的本地真实推理：Qwen3.5 27B 关闭 thinking，两次调用共 8,274 Token、约 83 秒。目标仍未修复，验证拒绝候选并清空最终补丁。这是开发单例，不是新增修复率成绩。[运行与失败分析](docs/local-issue-repair-20261019.md)。

第二轮在相同限制下试验模块导入和辅助函数上下文，两次锚点均被拒绝，总用量增至 8,877 Token。实验策略保持可选、默认保留原策略，最终相关回归 **213 项通过**。[对照及限制](docs/issue-context-round2-20261019.md)。

## 快速开始：无需模型 API

请使用源码仓库；上游 PyPI 包不包含本仓库的完整修复扩展。

```powershell
git clone https://github.com/Marshall0214/CoreCoder.git
cd CoreCoder
python -m pip install --no-cache-dir -e ".[dev,service,workflow,mcp-server]"
```

已有 corecoder 环境可直接使用。以下配置将状态、临时产物和缓存放在 D 盘：

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

先开启 Docker Desktop 的 Linux containers，确认虚拟磁盘在 D 盘，再构建镜像。详见 [沙箱配置](docs/execution-sandbox.md)。

```powershell
docker build -f deploy/sandbox/Dockerfile -t corecoder-test-sandbox:v1 deploy/sandbox
$env:CORECODER_RUN_DOCKER_TESTS='1'
python -B -m pytest tests/test_github_issue.py tests/test_sandbox_docker.py -q -p no:cacheprovider
python -B -m repairflow import-issue --url https://github.com/pallets/click/issues/3887 --config configs/issue-tasks/click-3887.json --output .tmp/github-issues/click-3887
```

导入只向 GitHub 发起公开 GET，不执行 Issue 中的命令，不安装仓库依赖，不调用模型。重复运行请使用新输出目录。
输出包括 `issue.json`、固定源码、可信测试、复现日志、`task.json` 和 `report.json`。

## 修复与审批服务

[完整流程指南](docs/unified-repair-flow.md) 提供可信任务包导出、历史精确回放及审批 API 的操作方法。历史任务回放需要此前保存的实验材料；上面的自包含测试无需这些旧产物。

```powershell
python -B -m service --port 8004 --timeout 1200 --output .tmp/repair-service
```

审批修复入口通过 `CORECODER_REPAIR_BUNDLES` 选择管理员维护的任务目录，执行前需要审批。Issue 导入目前仍为独立 CLI。默认快速开始不调用模型；后续新模型试验先关闭 thinking，和历史高思考实验分别记录。

`CORECODER_HOME` 可迁移撤销记录、授权、会话、历史、hooks、MCP 配置和价格覆盖文件；不设置时保留上游用户目录约定。服务工作进程使用任务独立状态目录。普通 Agent 的 Bash 工具与 Docker 验证沙箱属于不同执行入口。

## 代码与文档

| 路径 | 作用 |
| --- | --- |
| `corecoder/` | 上游 Agent 引擎、工具、模型接口、会话及 MCP Client |
| `repairflow/`、`configs/issue-tasks/` | 统一修复流程、可信 Issue 准备 |
| `sandbox/`、`deploy/sandbox/` | 容器策略与生命周期 |
| `service/`、`workflows/`、`mcp_servers/` | 任务 API、审批检查点和只读代码工具 |
| `evals/`、`docs/experiments/` | 评测框架、任务材料和版本化实验 |

建议从 [Issue 准备](docs/github-issue-preparation.md)、[修复流程](docs/unified-repair-flow.md)、[执行沙箱](docs/execution-sandbox.md) 和 [开发计划](plan.md) 进入。[上游同步说明](docs/upstream-sync-20261019.md) 记录本次整合与兼容处理。

原始 Agent 的学习内容见 [中文源码导读](article/00-index.md) 与 [English series](article/00-index_EN.md)。保留原作者署名及 MIT 许可证，个人新增能力与上游能力分别说明。

仅统计核心包：**30 个文件、物理 3117 行、净 2537 行**，引擎标识 `engine-1462_LoC`。不含 repairflow、sandbox、服务和评测扩展。核心包版本随上游为 **0.8.0**，不代表完整修复系统已发布同版本安装包。
