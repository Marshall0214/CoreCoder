# 第 1 轮：历史观察精简（2026-10-29）

## 运行前约定

- **事实：**上一轮 Click #3887 本地运行输入 51,697、输出 1,555 Token；历史观察重复携带读取正文及旧/新补丁正文，8 次调用后第 9 步预算预检停止。
- **假设：**历史正文改成引用与摘要，在保留当前源码、目标、约束、错误和测试反馈的条件下，可以减少请求输入；是否有助于修复需单独观察。
- **唯一主要改动：**`observation-policy=compact-v1`，不同时改变初始检索、模型、测试、轮数或预算。
- **先离线：**按原有九个请求状态重建精简请求，核对不变信息，统计前八个实际调用状态的请求估算；第九个被阻止状态单列。离线重建不是新模型轨迹。
- **再实测：**离线与必要回归通过后，只运行一次同任务、本地 Qwen3.5 27B、关闭 thinking 的候选。保留 60,000 Token、20 步、6 次编辑及原停止条件。
- **判据：**工程信息保留检查必须通过；分别报告请求缩减、实际用量、修复与回归结果，不把输入减少当作修复成功。
- **额度：**本阶段方法试验第 1/2 轮；本轮计划 1 次真实模型运行，启动前累计 0/6，失败也计入，不选择性重跑。

原 `full` 请求策略保持默认，精简策略显式开启；旧 `patch-v1` 不接受精简策略。完整动作、原始回答、版本证据、编辑校验及 Trace 继续留存，精简只影响模型请求视图。

## 结果

**已完成一次候选运行：Click #3887 通过约定的 1 项目标检查和 3 项正常行为检查，保留待审查补丁。**`accepted=false`，没有独立隐藏评分或上游完整套件验收，不更新历史 47/50。

**后续审查更新：**原公开检查仍通过，但六项新增样式保持诊断中候选仅通过两项，原始版本全部通过；审查结论为 `needs_revision`。候选尚不能视为完成修复，见[兼容性复核](compact-candidate-review-20261029.md)。原始记录和冻结证据不改写。

| 指标 | 历史 full 基线 | 本次 compact-v1 |
| --- | ---: | ---: |
| 模型调用 | 8 | 6 |
| 编辑申请 | 3 | 2 |
| 输入 Token | 51,697 | 24,105 |
| 输出 Token | 1,555 | 599 |
| 总 Token | 53,252 | 24,704 |
| 约定公开检查 | 最终目标失败，正常行为 3/3 | 目标 1/1、正常行为 3/3 |
| 交付 | 回滚，不交付 | 保留待审查补丁 |

总 Token 减少 **53.61%**，本次约 **39.72 秒**。这是不同轨迹的单次开发观察，不是严格因果或泛化结论；未换算现金费用，未调用云 API。

### 固定轨迹的离线核算

对同一组历史状态重建，原 `full` 请求可以逐字段复现。前八个实际调用状态的请求估算从 **50,956 → 30,293（−40.55%）**；目标、允许路径、公开测试、当前源码片段、版本、必需重读列表、剩余次数以及工具错误/测试反馈保持一致。

第九个原被阻止请求估算从 10,140 降至 4,760，单列而不计入八次实际调用汇总。它说明固定输入状态更短，不代表新模型必然继续或修复成功。所有数字是统一启发式请求估算，不能冒充实际 Token 节省。

### 模型实际如何修正

1. 第 1–2 步读取完整 `style` 和 `_ansi_reset_all`。
2. 第 3 步无条件清理输入 ANSI 序列，目标通过，但未指定新样式时原有颜色被清除，正常行为检查失败。
3. 第 4–5 步重新读取当前 `style`，其中仍有连续读取；该策略并未消除全部重复动作。
4. 第 6 步把清理操作置于“提供了新样式参数”的条件内，四项约定检查通过，保留净修改。

请求视图不重复传历史读取正文，补丁 old/new 以长度和哈希摘要表示。当前可编辑源码仍只来自原有 `fragments`；被更新或淘汰的历史读取标记 `content_available=false`，不能作为当前可编辑证据。错误、重读要求及公开失败反馈保留，完整动作和回答继续保存。

### 验收与限制

- 针对性测试 **173 passed**；全量 **1,782 passed、19 skipped，190.98 秒**；Ruff 通过。
- 真实 Docker **4 passed，45.23 秒**，包含精简历史下的锚点错误、重读和第三次编辑恢复；脚本响应不计模型修复成绩。
- 准备任务、配置、实现及模型摘要运行前后不变，无本任务遗留容器；原始源码未改写，补丁保留在独立候选工作区。
- 初次执行申请自动审批超时；后续预检因镜像标签查询失败停止，均未产生模型调用。核对原内容 ID 并恢复标签后，只执行了这一条实际候选轨迹，没有下载或重建镜像。提前改运行计数的申请曾被自动审批拒绝；最终计数依据实际报告更新。
- 当前补丁在提供任意新样式时清理 ANSI，可能影响未覆盖的颜色/背景/其他样式组合及非颜色控制序列，需人工审查；没有据此断言补丁全面正确。
- 单个已知开发任务缺少重复实验和陌生任务验证。工具说明与历史视图一起变化，不能把成功单独归因于某个字段，也不能声称修复率普遍提升。

**决策：**保留显式可选的 `compact-v1`，`full` 仍为默认；本次停止在第 1 轮，不自动开展第二轮或扩充任务。阶段累计真实模型任务运行 **1/6**、方法试验 **1/2**。

## 证据与使用

- [结构化对照及 65 项文件哈希](compact-observations-20261029.json)
- [实际报告](compact_observations_20261029/live/report.json)、[最终补丁](compact_observations_20261029/live/patch.diff)、[动作](compact_observations_20261029/live/actions.json)、[Trace](compact_observations_20261029/live/trace.jsonl)
- [运行前计划](compact_observations_20261029/run-plan.json)、[运行后完整性](compact_observations_20261029/postflight.json)、[完整运行时改动](compact_observations_20261029/implementation.patch)
- [离线估算明细](compact_observations_20261029/offline/summary.json)、[全量 JUnit](compact_observations_20261029/validation/full-junit.xml)、[Docker JUnit](compact_observations_20261029/validation/docker-junit.xml)
- [精简历史 Docker 用例报告](compact_observations_20261029/validation/docker-compact-report.json)、[来源与许可证](compact_observations_20261029/NOTICE.md)

当前实际 CLI 已支持以下选项；若复跑应换新输出目录并计入阶段额度，不保证重复得到相同结果：

```powershell
python -B -m repairflow repair-issue --prepared .tmp/github-issue-acceptance-20261019/click-3887-v2 --config configs/issue-tasks/click-3887.json --output .tmp/issue-compact-review-002 --mode ollama --model qwen3.5:27b --workflow symbol-recovery-v1 --observation-policy compact-v1
```

## 离线复核

从项目根目录运行，不进行模型推理；输出必须是新的项目 `.tmp` 子目录：

```powershell
python -B docs/compact_observations_20261029/audit.py --output .tmp/compact-review-001
```

输入为已冻结的 [10-29 模块读取运行](module-binding-20261029.md)，脚本先校验原始证据哈希，并确认 `full` 可以逐字段重建原请求。
