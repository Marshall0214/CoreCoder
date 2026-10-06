# 累计 Token 预算敏感性诊断 v1

## 问题与协议

此前 30k 预算下默认策略及阅读窗口策略都未开始修改。本次只诊断预算是否阻止任务进入修改阶段，不继续修改 Prompt、检索或历史组织策略。

新增入口 `python -m evals.budget_diagnostic`，协议为 `evals/real_defects/budget-diagnostic-v1.json`。复用固定开发清单的全部 7 个 Click 任务与同一准入环境。三档累计输入+输出预算为 30,000、60,000、100,000，每档各一次，共 21 次。

三档统一采用默认 agent-loop、检索 off、read_policy=full、output_policy=fixed、context_policy=none；固定 qwen3.5:27b、temperature=0、reasoning_effort=none、输出上限 2,048、上下文窗口 16,000、测试超时 15 秒。**统一提高工具轮数上限到 32，Worker 超时到 600 秒**，因此本轮 30k 也必须重跑，不能直接与此前 12 轮、180 秒记录配对。

只在本轮三档间改变累计预算。上下文窗口与累计预算是不同限制，不能把所有 budget_exceeded 都自动归因于累计预算；具体原因见各任务 Trace 的 budget_blocked 事件。轮数或超时仍可能成为新的瓶颈。

清单与协议分别校验 SHA-256；实际覆盖值写入每档 suite-report 的 diagnostic_overrides/config。原冻结清单、旧报告与默认 CLI 行为不改写。隐藏验收与预算诊断结果都不反馈给模型。

## 首次修改统计

父任务工具包装器比较合法源码写入前后的字节内容，实际变化才记录 source_changed；失败编辑与原样写回不算。变化后又撤销仍算曾发生修改，即使最终 changed_files 为空。

FixtureAgent 记录 agent_round，表示实际 Agent 循环尝试轮次，包含最终被预算预检查拒绝的请求轮次；不是模型完成调用次数。独立统计器从 Trace 提取：

- 首次变化的文件、工具、轮次与事件序号。
- 首次变化前完成的模型调用数、read_file 调用数。
- 首次变化前已知输入+输出 Token，以及预算记账 Token；包括产生该修改工具调用的模型响应。
- 未知用量调用数、总尝试轮次、总阅读调用数、残缺 Trace 行数。

未知用量按该调用实际预留计入预算记账，已知用量单独报告；失败服务请求的实际收费可能未知，不能将记账量当成精确账单。脚本模式没有真实 LLM 用量，字段为 null，不能假装测得 0 Token。没有 source_changed 时 first_source_change 为 null，不伪造首次修改轮次。

字节变化也可能包含换行格式变化，因此 source_changed 不是语义修复证明；仍需查看补丁与独立验收。本轮唯一修改在统一换行格式后也存在实质代码差异。

最终独立验收结果与实际修改记录分开：开始修改并不表示修复成功，净差异为空也不一定从未修改。

## 复现

在仓库根目录、corecoder 环境运行；output 必须使用新路径：

```powershell
python -m evals.budget_diagnostic --admission original=.tmp/real-defects/mixed-original-admission-v1/admission.json --admission crossfile=.tmp/real-defects/crossfile-admission-v2/admission.json --admission expansion=.tmp/real-defects/expansion-admission-v1/admission.json --output .tmp/real-defects/budget-diagnostic-replay
```

脚本链路验收加 `--mode scripted` 并使用新的 output。跨机器先重新准入三个目录，使用同一解释器，再传入新 admission 路径。

保存顶层 diagnostic.json、每档 suite-report/summary、每任务 Trace/补丁/评分及 Worker 环境记录。子矩阵每任务完成即保存；顶层在一档结束后更新。中断后保留子矩阵进度，complete=false，剩余任务不会伪装成已经运行；尚不支持原目录续跑。CLI 0 代表诊断矩阵完整，不代表模型全部修复通过。

## 验证

相关测试 37 passed；全量 583 passed、1 skipped；新增及修改文件 Ruff 通过。覆盖实际修改、无效编辑、原样写回、撤销修改、未知用量、残缺 Trace、脚本用量 null、三档条件固定和取消后的不完整矩阵。

脚本矩阵 21/21 通过，证据为 `.tmp/real-defects/budget-diagnostic-scripted-v1/diagnostic.json`，用于验证入口、工具与父评测器链路，不是模型成绩。

真实模型矩阵证据位于 `.tmp/real-defects/budget-diagnostic-live-v1/diagnostic.json`，具体结果完成后记在下文。所有任务均为已接触过修复的同仓库开发案例，单次预算扫描不能证明稳定成功率、留出表现或效率提升。

## 2026-10-06 实测结果

矩阵完整执行 21/21 次，CLI 返回 0 表示诊断完成。所有任务均为 budget_exceeded，停止原因全部为 cumulative_preflight，无轮数耗尽、超时或服务错误。下表的尝试轮次范围包含被预检查拒绝的最后一轮。

| 每任务预算 | 任务数 | 修复通过 | 发生实际修改 | 写入工具调用数 | 尝试轮次范围 | 已知输入+输出 Token 合计 |
| --- | --- | --- | --- | --- | --- | --- |
| 30,000 | 7 | 0 | 0 | 0 | 7–9 | 167,157 |
| 60,000 | 7 | 0 | 0 | 0 | 10–14 | 368,477 |
| 100,000 | 7 | 0 | 1 | 1 | 15–20 | 663,602 |

预算不是必然用满的目标，预检查可以在已知消耗低于上限时停止。全部 missing_usage_calls=0，全部首次修改统计均无残缺 Trace 行；本轮没有观测到未知用量。合计 1,199,236 已知 Token，模型在预算更高时继续探索，未出现任务成功率改善。

三档所有运行的实现哈希相同：`3e22a4a2f0606d36cebec4cacdc8a85e693d8f809c2517d19b12171f6141aaf9`。Worker 记录的 Ollama 模型 digest 均为 `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`。汇总复核证据为同目录 `analysis.json`；仍不能据此假定推理完全确定或单轮差异具有统计显著性。

### 唯一实际修改

100k 档的 `click-prompt-suffix` 在第 16 个 Agent 轮次、完成 16 次模型调用、读取 7 次文件后首次修改 `src/click/termui.py`；修改前已知及记账 Token 均为 **96,099**。随后下一轮预算停止。

修改将 prompt 输入函数参数从固定空格变为 prompt_suffix，但没有配套调整已输出的提示文本，也没有修复 confirm 路径。Target 与 Controls 均断言失败，且没有越界写入。不是有效修复，更不是因为 Worker 未完成而漏计了正确补丁。

剩余 20 次运行没有 edit_file/write_file 调用，不是编辑失败或修改后撤销导致 first_source_change 为 null。模型实际动作主要是阅读、搜索、列目录、维护待办和运行已有公开检查。

## 结论与下一步

在本轮所测模型与默认工作流下，将累计预算从 30k 增加至 100k 没有带来修复通过；最高档只有一次极晚的错误修改。因此不能把停止现象简单解释为预检查计算错误，也不建议继续单纯放宽总预算。

这没有证明更高预算或其他模型永远无法修复。当前更有依据的下一步，是给现有修复流程增加阶段控制：限制定位阶段预算、向模型提供预算状态、进入修改阶段时收敛工具与证据，并为公开验证留出预算。补丁正确性仍由父评测器独立判断，隐藏结果不反馈模型。

先在固定开发任务上验证阶段控制能否产生较早的有效修改，再开展多轮固定预算对照。预算扫描结果仅用于选择与诊断运行条件，不能写成检索收益或成功率提升。
