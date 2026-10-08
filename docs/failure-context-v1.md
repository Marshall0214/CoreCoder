# 失败后重新定位代码：开发集小批对照

本轮研究：在模型、失败日志、一次修正机会和源码上下文预算不增加时，利用公开测试执行证据重新选择代码，是否改善第二次修复。

## 方法

沿用现有首轮检索、结构化补丁、双重公开检查、独立评分和失败回滚。新策略只替换第二轮的代码选择：

1. 在隔离子进程中重新运行公开 `Reproduce`/`Preserve`，用标准库 `sys.settrace` 记录每个测试执行过的源码函数、行、异常事件和函数间调用边。
2. 只记录允许编辑的源码；不读取独立 Target/Controls、参考修复或帧局部变量。
3. 将运行位置映射到当前候选版本 AST。按失败/通过测试的函数命中情况，并结合与原检索种子的两跳调用邻域排序。
4. 保留前两个原始锚点和可装入预算的已修改函数，优先用邻域内新函数替换低优先级片段。上限仍为 6,000 源码字符、5 个完整函数，片段携带当前版本哈希。
5. 探测缺失、截断、跳过或无法执行时回退原有刷新种子。检查输入或源码被修改则失败关闭，不把它当正常反馈。

探测不调用 LLM，每组限时 15 秒；模型仍最多两次调用、累计 15,000 Token、上下文 16,000、每项流程限时 600 秒。反馈日志和测试代码不变，不追加诊断提示。执行到某个函数不证明根因就在该函数；这里是函数命中与调用邻域启发式，不是完整 SBFL 或精确 Python 调用图。

离线探测曾发现，单纯按失败命中排序会引入终端格式化与异常字符串化辅助函数，因此在首次模型调用前加入邻域限制和修改位置保留。前期离线记录保留在 `.tmp/real-defects/failure-context-v1-probe-admission/`，新增模型调用为零。

## 任务和比较

- 六项已知开发失败：`click-usage-empty`、`click-help-eagerness`、`click-resource-exception`、`click-shared-default`、`toolz-join-unmatched`、`more-predicate-sentinel`。
- 两项成功回归检查：`itsdangerous-none-salt`（原流程通过反馈修好）、`click-style-color-validation`（首轮即可修好）。
- `unchanged-feedback` 使用原有刷新种子；`failure-context` 使用上述执行证据重定位。各任务各组一次，交替运行顺序，共 16 次新任务执行。
- 同一模型摘要、任务、加强后的公开检查、固定断言和独立评分；首轮分别新请求，并在结束后核对是否相同。
- 这是针对已知失败的小批开发实验，不是完整 50 项成绩或新盲测。现有 32/50 的完整结果保持原样，新策略不接入默认 Agent/API。

运行输出：`.tmp/real-defects/failure-context-v1-pilot/experiment.json`；结束前 `complete=false`。每项保留请求、响应、执行探测、选择依据、候选差异和验证日志。

复现（先激活 corecoder，使用全新输出目录）：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp'
$env:TMP = $env:TEMP
python -B -m docs.experiments.failure_context_compare_v1 --output .tmp/real-defects/failure-context-v1-new
```

前置：已完成的 `system-comparison-v1-rerun` 任务清单、认证检查与冻结源码。所有新输出位于 D 盘，不下载模型或安装依赖。

## 参考工作与区别

- [AutoCodeRover](https://github.com/AutoCodeRoverSG/auto-code-rover)：借鉴 AST 结构搜索与测试辅助定位；本轮不实现其统计故障定位或完整 Agent。
- [RepairAgent](https://arxiv.org/abs/2403.17134)：借鉴测试失败后重新收集代码，而不是反复使用固定上下文；本轮不扩大自主工具循环。
- [SWE-Doctor](https://github.com/SWE-Doctor/SWE-Doctor)：借鉴用测试运行证据支撑诊断；本轮不生成新测试、不驱动 pdb、不记录局部变量或增加 LLM 诊断阶段。

这是机制借鉴，不是复现这些论文；相关工作的模型、任务与预算不同，不比较它们的成功率与本项目的 64%。

代码：[执行探测](experiments/failure_trace_probe_v1.py)、[重定位策略](experiments/failure_guided_context_v1.py)、[配对执行器](experiments/failure_context_compare_v1.py)、[测试](../tests/test_failure_guided_context.py)。

## 完整结果与决定

| 方案 | 通过 | 正常行为通过 | 调用 | Token | Worker 总秒数 |
| --- | --- | --- | --- | --- | --- |
| unchanged-feedback | 2/8 | 8/8 | 15 | 48,529 | 236.3 |
| failure-context | 2/8 | 8/8 | 15 | 47,870 | 240.9 |

首轮请求 8/8 完全相同，首轮回答 8/8 完全相同；7 项第二轮实际加入了原上下文之外的新函数。六项既有失败均未修好；none-salt 与 style 两项成功保留，无新增成功、无丢失成功。每组最终回滚六项失败，正常行为通过包含这些回滚结果，不代表八项都修好。

Token 48,529 → 47,870，减少 659（约 1.4%），Worker 耗时略增。这是单轮小样本，不能认定稳定的成本收益。探测未使用私有评分，模型输入只有重新选择的当前源码；完整 50 项的 32/50 结论不变。

**决定：不采用，不扩大运行。**相关代码与日志保留用于诊断。本轮说明：在这些任务上，仅用执行函数及邻域重新组织代码并未改善修复；不能进一步推导执行信息无用或模型推理是唯一原因。下一步若继续，应从已保存的失败断言和候选补丁逐项确认缺失的语义证据，避免继续按覆盖率或重试次数盲调。

**验证：**新增 7 项测试通过；全量 1,318 passed、4 skipped；Ruff 与冻结输入哈希检查通过。没有重跑 HTTP/容器验收，也未修改默认 Agent/API。

[逐项紧凑结果](failure-context-v1.json)保留完整状态、消耗、新增函数与采用结论；原始运行日志位于 D 盘试验目录。
