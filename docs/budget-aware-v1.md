# 预算与源码阅读改造 v1

## 需求与实现

旧混合开发集单轮 7 个任务均在修改前预算停止。本次不增加 30,000 累计 Token 预算，增加可单独配置的策略；默认值仍保持旧行为，历史清单不改写。

| 配置 | 旧默认 | 新选项 | 行为 |
| --- | --- | --- | --- |
| output_policy | fixed | remaining | 本次输出上限取配置上限、累计剩余空间、上下文剩余空间的最小值 |
| read_policy | full | bounded | read_file 最多 120 行、6,000 字符，保留行号和继续读取位置 |
| context_policy | none | read-dedup | 请求视图中将重复的相同源码片段替换为指向保留阅读的引用 |
| context_policy | none | read-window | 以 6,000 字符为阅读正文选择目标，优先保留较新片段；较早片段改为显式省略通知 |

动态输出以估算输入为依据，最低可用输出为 min(256, 配置输出上限)。不足最低输出时仍停止；输入本身已超过剩余预算时，不能靠缩小输出继续。估算可能不准确，仍保留返回用量检查，超预算后不会执行本次工具调用。未知用量按本次实际预留记账；这不是服务商账单硬上限。

TracedLLM 只对当前请求设置输出上限，下一次恢复原配置，兼容结构化输出参数。Trace 记录 effective_max_output_tokens。模型可能在缩小的输出上限内无法完成较大补丁；不能保证所有预算停止消失。

BoundedReadTool 的描述引导先 grep/search_code 定位，再按 offset 读取。大于 120 的显式 limit 也会被截断；单行过长会明确标注行截断。没有新增检索工具或自动 AST 定位，仍依靠模型选择工具。

重复压缩不修改原始历史和 Trace，不概括或删除不同片段。必须满足同文件、相同返回内容、当前文件哈希与阅读凭据一致、完整片段仍保留在本次请求中。文件改动或保留片段被既有压缩移除时，恢复原始消息。片段凭据与完整文件覆盖凭据分开保存，不能用局部阅读授权 read-cover。

read-window 与 read-dedup 是两个独立选项，不能把被省略的正文当作保留阅读引用。阅读窗口保留完整片段，不从函数中间静默截断；通知包含路径、原始 offset 和调用 ID，并明确需重新定位/读取。原始 Trace 与历史未被窗口修改，编辑/测试结果也不被窗口删除。短返回若比省略通知更便宜则保留，实际正文可能超过 6,000 字符选择目标，Trace 单独记录 unprofitable_reads 与实际 retained_read_chars。其他消息与通知仍计入 Token。旧源码证据可能不再出现在当前请求，这是效率与证据完整性的取舍。

实现：`evals/read_policy.py`、`evals/runtime.py`、`evals/context_policy.py`、`evals/worker.py`。单任务 CLI 增加 output/read/context policy 参数。

## 实验入口与边界

新增冻结清单 `evals/real_defects/budget-aware-suite-v1.json`，与旧清单固定同一 7 个任务、模型、温度、预算、轮数和超时，只启用上述三个策略。旧 development-suite-v1 清单缺少的新字段固定解释为 fixed/full，其原文件不改写。

这是三项策略组合的开发诊断，不能归因为单一检索策略或某一项改造的效果。若发现收益，需要进一步逐项消融及多轮复跑。

```powershell
python -m evals.real_suite --suite evals/real_defects/budget-aware-suite-v1.json --mode live --repeat 1 --admission original=.tmp/real-defects/mixed-original-admission-v1/admission.json --admission crossfile=.tmp/real-defects/crossfile-admission-v2/admission.json --admission expansion=.tmp/real-defects/expansion-admission-v1/admission.json --output .tmp/real-defects/budget-aware-replay
```

使用新的 output 路径。单任务可用 `python -m evals.real_tasks` 原有参数加 `--output-policy remaining --read-policy bounded --context-policy read-dedup`。不需要提高 token-budget。使用阅读窗口版本时将 suite 改为 `budget-aware-suite-v2.json`，或单任务 context-policy 改为 read-window。

## 验证

单元测试覆盖：旧策略拒绝但动态输出可容纳的请求、低于最小输出时停止、返回实际用量超预算、未知用量记账、上下文空间限制、请求级参数恢复、行数/字符截断、片段凭据隔离、重复阅读引用及文件变化/锚点移除恢复、不同文件的相同内容不合并。

最终离线证据使用 `.tmp/real-defects/budget-aware-{unchanged,reference,scripted}-v2`。v1 是修改片段凭据兼容逻辑前的记录，保留但不与最终结果合并。真实模型对照使用同一代码版本重跑默认策略和新组合策略各一次，分别保存在 `.tmp/real-defects/budget-policy-control-v1`、`.tmp/real-defects/budget-policy-aware-v1`。具体结果见下文。

## 首轮对照：重复阅读压缩没有解决问题

同版本默认与 v1 组合策略各 7 次，全部 budget_exceeded、未修改源码，修复通过均 0/7。新策略各次的重复阅读压缩计数均为 0，因为模型主要读取不同片段；不能把停止原因名称改为 minimum_output_preflight 当成预算问题已解决。

Trace 表明不同历史片段仍随每次请求重新计费，停止时输入估算已大于剩余预算，缩小输出也不能容纳请求。保留首轮失败结果，据此增加 read-window 选项并冻结 v2 清单。v2 另在同版本下重跑旧策略控制组，不拿不同实现版本的结果直接配对。

最终代码回归：578 passed、1 skipped，Ruff 通过。新增测试同时验证窗口保留最近片段、明确标注省略、保留原始消息，以及保留短返回时的统计口径。

## 阅读窗口对照结果

最终窗口策略离线验收 21 次均符合预期：unchanged 7 次失败、reference 与 scripted 各 7 次通过。证据为 `.tmp/real-defects/budget-window-{unchanged,reference,scripted}-v1`。

同一实现版本默认策略与窗口组合策略各跑一次，完整矩阵均 7/7，均 0/7 修复通过，全部 budget_exceeded，未产生源码修改。没有证明任务成功率或 Token 成本改善。

| 任务 | 旧策略已知 Token | 窗口策略已知 Token | 单次请求最大省略阅读数 | 输出上限缩减调用数 |
| --- | --- | --- | --- | --- |
| help-eagerness | 26,423 | 27,018 | 3 | 0 |
| flag-default-map | 22,097 | 25,717 | 0 | 0 |
| resource-exception | 20,442 | 24,965 | 3 | 0 |
| flag-envvar | 21,197 | 27,397 | 4 | 0 |
| prompt-suffix | 26,751 | 27,229 | 4 | 0 |
| invoke-missing | 27,104 | 28,023 | 1 | 0 |
| shared-default | 27,181 | 28,527 | 2 | 1 |
| 合计 | 171,195 | 188,876 | — | 1 |

窗口组已知 Token 合计反而增加约 10.3%。每次输入减少，不保证总消耗减少：模型可能继续更多探索，直到累计预算停止。窗口策略仍无法容纳最后一轮输入；动态输出只能处理输入已经能放下、但完整输出预留放不下的情况。单轮开发结果也不足以判断稳定收益或退化。

证据：`.tmp/real-defects/budget-window-control-v1/suite-report.json`、`budget-window-window-v1/suite-report.json`、`budget-window-comparison-v1/comparison.json`。比较程序核对任务 ID、实现哈希及准入检查哈希一致。两组均无 missing_usage_calls；隐藏检查未进入模型输入。对应实验实现哈希以 comparison.json 为准。

对照完成后只修正了窗口统计：短正文比通知更便宜时保留，并将这部分正文正确计入 retained_read_chars，增加 unprofitable_reads。该修正没有改变发送给模型的消息，未重跑模型。原始模型结果保留各自实现哈希，不能将其标成修改后代码版本的新实验。

## 当前结论与下一步

动态输出单元测试证明可以避免预留完整输出导致的过早停止，但本轮真实任务主要是下一次输入已经超过剩余预算。局部阅读、去重与历史窗口都不能保证模型及时开始修复。因此暂不把这组策略设为默认，也不继续重复同一低预算下的三轮基线。

下一步先做预算敏感性诊断，区分总预算不足与探索工作流低效，再考虑给模型显式预算状态、划分定位/修改/验证阶段，并为后两阶段保留预算。提高预算的诊断必须单独记录，不能当作固定预算效率提升。新机制具备可测的边界，但实际任务预算停止仍未解决。
