# Harness² 合成与交付修复：完整单项验收（2026-11-06）

**本轮完整链路通过。** 从原始缺陷重新执行 `toolz-join-unmatched` 的 base1、inv1、dom1、agg1，完成官方合成、经验审查、自动候选交付，再对交付的 agg1 进行独立评分：**Target 1/1、Controls 1/1**。没有复用旧候选，没有人工修改候选补丁，没有后置人工恢复交付。

## 修改了什么

修改的是本项目的 Harness² 接入层，官方递归核心及既有修复器保持原版本。

1. **隔离候选选择依赖。** `harness2_batch.public_selection()` 将公开候选选择作为独立 job 交给现有 Python 3.11 修复进程。3.12 控制器继续运行官方核心，不再导入修复执行包及其模型 SDK。选择 job 只接收公开收据、任务/源码哈希和既定配置；不接收独立评分或参考补丁，新增推理为 0。PPC 完成状态在选择之前记录，防止交付故障掩盖上游失败。
2. **优先提供决策材料。** `harness2_reader` 的 v2 快照增加 `review_packet`：完整的短补丁、候选指导、指导差异、公开终态、动作计数与事件位置。正文来自原文件，携带 ID/哈希；相同正文共享引用，超过 4,000 字符的文件保留原文读取指针。没有 LLM 摘要、评分排名或隐藏答案。
3. **明确提交阶段。** 编辑器每次请求都看到剩余请求数；20 次上限中的最后 2 次留给最终 JSON 和格式纠正，届时读取请求被拒绝。允许有证据支持的保持原指导，经验不足时允许返回 null；不会替模型伪造合规输出。系统契约同时说明：此适配器使用只读 JSON 动作和最终 JSON，上游任务文本里的磁盘编辑、notes-only 回复描述不适用于本接口。

修复器公开反馈仍最多 20 次，本轮没有增加其限制。模型为本地 Qwen3.5:27b、thinking=false；无累计/输出 Token 截止。源码、数据、既有 Docker 镜像、无网络及资源约束、评分协议与前轮相同，所有新增数据在 D 盘，付费模型 API 调用 0。

## 完整执行结果

| 阶段 | 编辑器调用 / 读取 | 修复探索调用 | 公开反馈修正 | 公开检查 |
| --- | ---: | ---: | ---: | --- |
| base1 原始指导 | — | 7 | 1 | Reproduce 1/1、Preserve 1/1 |
| inv1 通用指导 | 11 / 10 | 8 | 1 | Reproduce 1/1、Preserve 1/1 |
| dom1 领域指导 | 2 / 1 | 6 | 1 | Reproduce 1/1、Preserve 1/1 |
| agg1 合成指导 | 4 / 3 | 10 | 1 | Reproduce 1/1、Preserve 1/1 |
| 经验审查 | 4 / 3 | — | — | 返回 experience=null，无新经验准入 |

官方核心 `done=1、failed=0`，四个编辑会话均正常返回，格式纠正 0 次。官方采纳 agg1，公开候选规则也选择 agg1，随后自动进行独立验收；不依赖前轮恢复脚本。

前轮合成读取 20 次后失败，本轮只读取 base1、dom1、inv1 各自反馈附近的原文页，4 次调用后提交。没有触及末两次请求的提交保留机制；该机制由自动化测试覆盖。本次同时修改了材料组织和提交契约，单次试验不能将收敛收益完全归因于其中一个因素。

四次修复的探索仍因重复动作停止，均通过一次公开反馈把 `iteritems(d)` 改为 `d.items()`。四个最终工作区哈希相同；实际独立评分只运行在交付的 agg1，不能计成四项独立缺陷修复。

## 成本与可观测性

| 项目 | 前轮 | 本轮 |
| --- | ---: | ---: |
| 完成的修复探测 | 3 | 4 |
| 完整 PPC | 失败 | 通过 |
| 原生本地调用 | 76 | 56 |
| 原生 Token | 831,429 | 573,462 |
| 自动交付 | 依赖错误，后置恢复 | 正常交付 agg1 |

本轮探索 31 次、162,389 Token；反馈 4 次、159,801 Token；编辑和经验审查 21 次、251,272 Token。总耗时约 459.0 秒，包括身份/入场检查与最后独立评分，不包括归档。前轮失败流程与本轮完整流程的阶段数不同，该表是已知单项的工程观测，不是等总计算预算的修复率实验或稳定的成本节省结论。

12 条原生 Trace、56 个 GENERATION 已回读，逐调用 Token 与本地日志一致。[Langfuse 完整流程概览](http://127.0.0.1:3300/project/corecoder-issues/traces/dcd4fd07735ea291c20525eec9fae0ed)关联这些真实 Trace 和独立验收，共 14 个普通 Span，概览自身不重复生成推理用量。

后置审计核对了生成指导到修复 job、31 份有效探索请求与 4 次反馈请求的传递；每份预置短正文和读取结果均与快照原文/哈希一致。独立评分在 PPC 结束后执行，历史完整批次报告和原 14 份 Agent 基线文件哈希不变。

## 验证与复现

- Python 3.11 相关回归：**79 passed、2 skipped**。新增覆盖短证据原文/别名/长文件指针、提交阶段拒绝继续读取、PPC 失败后的公开交付及 job 私有字段拒绝。
- Python 3.12 控制器 unittest：**24 tests OK**；另以真实 3.12 → 3.11 边界执行一次公开候选选择，模型调用 0，控制器未导入模型 SDK。
- Ruff、Diff 空白检查与冻结证据的逐文件 SHA-256 校验通过。

机器摘要：[`harness2-ppc-v2-20261106.json`](harness2-ppc-v2-20261106.json)。完整证据见 [`harness2_ppc_v2_20261106/manifest.json`](harness2_ppc_v2_20261106/manifest.json)，保留执行时实现、全部原生请求/响应、快照、公开测试、独立评分、跨环境烟测、回执和辅助脚本，并关闭 Git 换行转换。前轮失败证据仍在 [原报告](harness2-ppc-20261106.md)，未被覆盖。

本机已有模型、数据、依赖与镜像时，使用归档 `helpers/validate_harness2_ppc_v2_20261106.py` 和全新 `.tmp/` 输出目录复现：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHON_DOTENV_DISABLED='1'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH="$PWD\.tmp\langfuse-deps;$PWD\.tmp\workflow-deps;$PWD"
$env:TEMP="$PWD\.tmp"
$env:TMP=$env:TEMP
$env:CORECODER_LANGFUSE_ENABLED='1'
$env:CORECODER_LANGFUSE_ENV_FILE="$PWD\.tmp\langfuse-local\.env"
$env:CORECODER_TEST_BACKEND='docker'
$controller='C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $controller -B docs/harness2_ppc_v2_20261106/helpers/validate_harness2_ppc_v2_20261106.py `
  --output .tmp/harness2-ppc-NEW
```

归档审计脚本在 3.11 环境使用；原始记录保留执行机器的绝对路径，跨机器需先重建数据来源。未运行新的 50 项批次；原完整批次仍为 24/50 与 27/50。本轮证明完整流程可以运行，**没有证明 Harness² 比原始指导更能修好缺陷**；下一步若研究收益，应先选择原始指导加反馈仍失败的任务，冻结协议后进行小规模对照。
