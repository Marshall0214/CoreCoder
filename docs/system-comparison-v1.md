# 原始 CoreCoder 与修复工作流：完整 50 项对照

本轮重新运行同一批 50 项任务，以统一评分比较历史 CoreCoder、仅检索方案和完整修复流程。本轮全部 150 次执行已完成；历史 42% → 50% 与 14/30 → 17/30 不并入本轮。

## 比较对象

| 组别 | 实际执行流程 | 每项限制 |
| --- | --- | --- |
| original | 历史 Agent 循环；原生 read/glob/grep/edit/write/todo/bash 七个工具 | 最多 12 轮，允许主动执行公开检查 |
| retrieval | AST 符号和类范围检索；结构化唯一锚点补丁 | 一次模型调用，不提供执行失败反馈 |
| full | 相同检索与补丁协议；双重公开验证；一次失败反馈；无效补丁回滚 | 最多两次模型调用 |

历史源码取自新增评测之前的提交 `84b320e2d21628a2c00934aa0a2343139c16a49e`，逐文件提取并冻结哈希。历史 `__init__` 使用绝对导入，因此适配器显式选择快照中的 Agent，避免意外加载当前版本。没有改写历史 Agent 循环、提示词或原生编辑工具。

original 是**受控七工具基线**：外接共同模型客户端、预算、工作区范围和公开测试命令约束，不开放子 Agent、网络抓取或任意 Shell 命令。它不代表无限预算下完整上游产品的能力。

## 共同协议

- 五个真实仓库、50 个固定缺陷，历史开发标签 30 项、历史留出标签 20 项；每组全部任务运行一次，不按结果筛选或补跑失败项。
- Ollama `qwen3.5:27b`，固定模型摘要；禁用思考、temperature=0、top_p=1，每次输出上限 2,048 Token；各组每项共同上限 15,000 Token、16,000 上下文、600 秒。
- 运行前重新验收每项：起始版本目标测试失败、正常行为测试通过；参考修复两组均通过。参考修复仅用于离线认证，不进入模型输入。
- 同一组独立 Target/Controls、公开 Reproduce/Preserve 及固定断言用于全部方案评分。44 项具有认证固定断言，另 6 项只有公开检查，逐项记录。
- Click Context 栈保持检查 v2、固定乘积预期检查统一加入各组。全部模型工作区均可读取同样的公开检查及固定断言；独立评分检查不进入 Worker。
- 三组使用独立起始工作区与新模型请求，按任务编号轮换执行顺序。保存请求、响应、工具事件、补丁、检查日志、状态、Token 和耗时。
- 最终通过要求：执行正常结束、修改范围合法、独立目标及正常行为检查通过、公开及固定断言均通过。预算停止、截断、超时、验证失败均保留在分母。

## 限制

这是已知任务上的工作流整体比较，三组工具和编排不同，不能将全部差异归因于检索算法。full 允许额外一次修正，因此须同时比较成功数、调用数与 Token；预算上限相同不意味着实际计算量相同。

任务由人工根据公开修复构造，多数为单文件缺陷，关联函数会跨分组。历史留出任务此前已经运行过，不能在本轮宣称全新盲测，也不能将结果外推到任意仓库或 SWE-bench。

## 执行记录

首轮 `system-comparison-v1-final` 因 Windows 当前目录锁定回滚工作区而中止，7 条已评分记录及所有请求日志原样保留，不混入重跑。修复：仅历史工具组将当前目录切入任务工作区；结构化流程始终从外部目录执行，确保可以恢复工作区。新增真实目录恢复测试覆盖该路径。

正式重跑输出：`.tmp/real-defects/system-comparison-v1-rerun/`。`manifest.json` 冻结全部来源与配置；`experiment.json` 保存逐项结果，结束前 `complete=false`。

复现命令（先激活 corecoder 环境；使用新的输出路径）：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp'
$env:TMP = $env:TEMP
python -B -m docs.experiments.system_comparison_v1 --prepare --output .tmp/real-defects/system-comparison-v1-new
python -B -m docs.experiments.system_comparison_v1 --output .tmp/real-defects/system-comparison-v1-new
```

代码：[对照执行器](experiments/system_comparison_v1.py)、[历史 Agent 与模型适配器](experiments/system_comparison_worker_v1.py)、[回归测试](../tests/test_system_comparison.py)。所有新输出保存在 D 盘，不改变默认 Agent/API。

## 正式完整结果

| 方案 | 正常完成且统一通过 | 正常行为通过 | 模型调用 | Token 总数 | 每项平均 Token | Worker 总秒数 |
| --- | --- | --- | --- | --- | --- | --- |
| original | 0/50（0%） | 50/50 | 184 | 509,491 | 10,190 | 514.2 |
| retrieval | 25/50（50%） | 48/50 | 50 | 143,193 | 2,864 | 634.0 |
| full | 32/50（64%） | 50/50 | 71 | 216,492 | 4,330 | 900.9 |

成本包含全部成功和失败，不只统计通过项；Worker 耗时包括流程内测试，不含流程结束后的共同独立评分。
相同预算上限不等于相同实际用量。缺失调用结果、缺失 usage 和 Provider 失败数量均在 JSON 中单列。

仅检索 → 完整流程：**25/50 → 32/50，50% → 64%，提高 14 个百分点**。实际调用 **50 → 71**，Token **143,193 → 216,492（增加 51.2%）**，每项平均 **2,864 → 4,330**。正常行为检查通过 **48/50 → 50/50**；这包含失败任务回滚后的结果，不表示额外修好了两个缺陷。

原始组 **50 项均预算停止，0 项正常完成，但有 2 个最终补丁独立验证通过（4%）**，分别为 `toolz-accumulate-empty` 和 `toolz-merge-mapping`。因此既不能说它“完全不会修复”，也不将 `0% → 64%` 作为简历主结论。原始组较短耗时来自提前停止，不能解读为更高效率。

| 分组 | 数量 | original | retrieval | full |
| --- | --- | --- | --- | --- |
| development | 30 | 0 | 14 | 20 |
| heldout | 20 | 0 | 11 | 12 |

| 缺陷类型 | 数量 | original | retrieval | full |
| --- | --- | --- | --- | --- |
| callback_and_exception | 7 | 0 | 2 | 4 |
| defaults_and_boundaries | 14 | 0 | 7 | 8 |
| numeric_consistency | 9 | 0 | 6 | 7 |
| parameter_validation | 8 | 0 | 7 | 8 |
| state_and_consumption | 7 | 0 | 1 | 2 |
| type_and_representation | 5 | 0 | 2 | 3 |

| 仓库 | 数量 | original | retrieval | full |
| --- | --- | --- | --- | --- |
| mahmoud/boltons | 7 | 0 | 3 | 5 |
| more-itertools/more-itertools | 24 | 0 | 12 | 16 |
| pallets/click | 10 | 0 | 3 | 3 |
| pallets/itsdangerous | 3 | 0 | 2 | 3 |
| pytoolz/toolz | 6 | 0 | 5 | 5 |

各组执行状态：

- original：`{"budget_exceeded": 50}`；最终代码独立验证通过 2/50。
- retrieval：`{"completed": 46, "invalid_patch": 3, "output_truncated": 1}`；最终代码独立验证通过 25/50。
- full：`{"failed_public_validation": 14, "completed": 32, "invalid_patch": 3, "output_truncated": 1}`；最终代码独立验证通过 32/50。

完整流程相对仅检索新增通过 7 项，丢失通过 0 项。
新增：boltons-backoff-constant, boltons-chunked-bytes, itsdangerous-none-salt, more-bucket-missing-key, more-combination-size, more-last-typeerror, more-permutation-exception。
丢失：无。

完整组触发反馈 21 次，保留修正 7 次，最终恢复起始源码 18 项。
两组首轮请求完全相同 50/50，首轮响应逐字相同 50/50。7 个保留修正的任务恰好等于 7 个新增通过任务，因而本轮新增成功均来自后续失败反馈修正。一般情况下相同提示不保证相同输出；本轮通过逐项请求和响应核对确认，而非预先假设。

原始组工具错误统计：`{'bash': 22}`。本轮预算停止主导原始组结果；只能表述为固定限额下的受控基线，不写成原始 CoreCoder 通用成功率。

中止轮另记录 13 份请求、12 个返回事件、36,251 个已知返回 Token，均未并入正式对照。另 1 个无返回记录的请求消耗未知，不计为零。

剩余 18 项失败：14 项公开验证失败、3 项补丁格式/锚点失败、1 项输出截断。Click 两组均 3/10，未获得反馈收益；状态与消费类仅 2/7 通过。后续应优先诊断这两类失败，不再将追加反馈次数视为普遍有效。

**验证：**全量 1,311 passed、4 skipped；新增 6 项测试通过；Ruff 通过。四项跳过沿用两项可选 SQLite 检查点及两项 Windows 链接检查；本轮没有重跑 HTTP 或容器验收。

逐项紧凑证据：[system-comparison-v1.json](system-comparison-v1.json)。完整请求、响应、补丁和检查日志保留在 D 盘正式输出目录。
