# budget-sensitivity-v1：首次修改前开销与预算诊断

更新：2026-10-04。本轮是独立诊断，不是检索/上下文优化实验。原 30,000 Token 失败结果保留，不用增加预算后的结果替代原基线。

## 问题与预先固定的协议

read-cover 四次 pilot 均在首次修改前耗尽累计预算。先确认：预算更充足时，模型是否开始修改并完成独立验收？若仍失败，区分不完整补丁、轮数、时间和累计预算等限制。

新增 Trace 阶段诊断记录首次 edit_file/write_file **尝试**之前的 LLM 调用、实际已知用量、未知用量调用和工具调用；编辑失败也构成尝试，不能当作成功写入。没有编辑时统计整个已观察运行。缺失 usage 或调用失败令阶段总用量为 null，已知部分另存，不记作零。分析不保存模型内部推理，也不提供完整的推理阶段划分。

对 pagination-cursor 与 lease-lifecycle 各执行两次：30,000 和 60,000 Token。保持关键词、search-history=full、context-policy=none，**不同时改变上下文策略**。模型 Qwen3.5:27b、temperature=0、reasoning_effort=none；输出 2,048、轮数 12、上下文估算 16,000、Worker 180 秒、测试 15 秒、搜索正文 6,000 字符固定。分页先 30k 再 60k，租约反序。每组每任务一次，总共四次；结果只用于诊断，不估计稳定成功率或统计显著提升。

两种预算在同一代码版本重新运行，不将旧 pilot 作为共同版本控制。每次从干净工作区开始，失败计入结果、不选择性重跑。增加预算提高资源上限，不是算法效率提升；预算预检仍为下一轮估算输入与输出预留，实际用量可能低于上限。

## 已有运行的阶段诊断

read-cover-v1 四次 pilot 都没有编辑尝试，整个运行用量即首次编辑前用量：

| 任务/策略 | LLM 调用 | 已知实际 Token | 修改前工具 |
| --- | --- | --- | --- |
| pagination / none | 7 | 27,409 | 4 次计划、2 次搜索、4 次读取 |
| pagination / read-cover | 8 | 27,483 | 4 次计划、1 次搜索、3 次读取 |
| lease / none | 6 | 26,715 | 2 次计划、1 次搜索、14 次读取 |
| lease / read-cover | 5 | 26,924 | 2 次计划、3 次搜索、14 次读取 |

所有用量均已知，没有发生修改后测试的成本。读取和计划逐轮进入历史，工具 Schema 也参与后续请求；此表不能把实际输入 Token 精确分摊给各工具。

## 复跑

```powershell
python -m pytest tests/test_trace_diagnostics.py -q
python -m evals.diagnostics .tmp/evals/read-cover-v1/pilot --output .tmp/evals/budget-sensitivity-v1/prior-phase-diagnostics.json
foreach ($budget in @(30000, 60000)) {
    python -m evals --suite evals/fixtures/localization-v1 --task pagination-cursor --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --search-history full --context-policy none --token-budget $budget --output ".tmp/evals/budget-sensitivity-v1/pilot/pagination-cursor/$budget"
}
foreach ($budget in @(60000, 30000)) {
    python -m evals --suite evals/fixtures/retrieval-overlap-v1 --task lease-lifecycle --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --search-history full --context-policy none --token-budget $budget --output ".tmp/evals/budget-sensitivity-v1/pilot/lease-lifecycle/$budget"
}
python -m evals.diagnostics .tmp/evals/budget-sensitivity-v1/pilot --output .tmp/evals/budget-sensitivity-v1/pilot-phase-diagnostics.json
```

新实验使用新目录；CLI 返回码 1 表示存在未通过任务，不等于基础设施故障。原始产物位于 Git 忽略的 .tmp，需要另行备份。

## 执行结果

| 任务/预算 | 状态 | 总实际 Token | LLM 调用 | 首次编辑前调用 / Token | 修改文件 |
| --- | --- | --- | --- | --- | --- |
| pagination / 30k | failed_verification | 17,475 | 5 | 3 / 9,020 | query.py |
| pagination / 60k | failed_verification | 21,664 | 6 | 4 / 12,827 | query.py |
| lease / 60k | budget_exceeded | 49,952 | 9 | 7 / 34,690 | acquire.py、lookup.py |
| lease / 30k | budget_exceeded | 27,659 | 6 | 未编辑；6 / 27,659 | 无 |

两种预算主验收均 **0/2**，候选独立验收也均 0/2。四次可见回归通过；无基础设施故障或 usage 缺失。轮数、时间和上下文窗口限制未成为本轮终止原因。温度为零仍存在轨迹波动，两项各一次的结果不能估计稳定成功率或预算与效果的普遍关系。

**分页：**两组均修复 query.py 的复合排序键筛选，但未修 paging.py 的续页游标，四项独立目标测试仍失败。两组正常结束且实际消耗低于 30k；这两次运行的失败不能归为预算截断。模型已阅读相关模块，遗漏修复与可见测试未覆盖边界共同导致了提前收尾。目标测试只由父进程验收，未向模型泄露。

**租约：**30k 组在编辑前终止，之前调用计划三次、搜索一次、读取十四次。60k 组修复创建单位和续租定位，目标测试通过 2/4，遗漏 expiry.py 的到期相等边界；未执行可见测试工具便再次预算终止。其下一次输入估算 8,649，加输出预留 2,048，需要 10,697，而剩余只有 10,048。30k 组对应需求 9,681，剩余 2,341。

60k 轨迹首次编辑前已消耗 34,690，说明该条轨迹无法完整放进 30k 预算；这不证明两组运行在相同调用位置必然一致。高预算允许出现部分修复，却没有完成全部缺陷和收尾。不能将部分目标通过替换正式成功，也不能把更多资源称为优化收益。

## 验证与版本

新增阶段诊断测试覆盖首次编辑失败、后续用量排除、没有编辑、未知 usage 和失败调用。诊断测试 5 项通过；全量 **271 passed、1 skipped，45.00 秒**；Ruff 通过，Windows 符号链接项仍跳过。

四次运行源码哈希相同：`d79c417ef35d2ea01958a4a118fb62c8c71e109b5313b87f090a17ce1aa3c283`。同任务两组的 fixture、grader、manifest、规范化 Prompt 和工具 Schema 哈希相同，配置仅 token_budget 不同。

- [pagination 30k](../.tmp/evals/budget-sensitivity-v1/pilot/pagination-cursor/30000/summary-97c6337397.md)
- [pagination 60k](../.tmp/evals/budget-sensitivity-v1/pilot/pagination-cursor/60000/summary-b72ff62d9f.md)
- [lease 60k](../.tmp/evals/budget-sensitivity-v1/pilot/lease-lifecycle/60000/summary-7a1bb67a0d.md)
- [lease 30k](../.tmp/evals/budget-sensitivity-v1/pilot/lease-lifecycle/30000/summary-798e35c575.md)

同名 JSON 保存完整报告；阶段统计为 `.tmp/evals/budget-sensitivity-v1/pilot-phase-diagnostics.json`，旧运行诊断为 `prior-phase-diagnostics.json`。仅记录完成调用的已知 usage，失败提供商尝试的计费仍未知。

## 下一步决定

保持原 30k 预算和已有默认策略，不扩大本轮预算扫描。下一项先设计**契约覆盖检查的独立干预**：按症状追踪相关契约、涉及实现与已验证/未验证行为，避免读到契约却遗漏第二处修复。清单应来自模型可读的缺陷描述与仓库契约，不使用参考修改文件或独立目标测试。

该工作流/Prompt 干预须单独版本化，与上下文覆盖、预算提升分开对照。先确认清单确实覆盖多处问题、不会产生大量重复计划开销，再用固定预算小样本测试；本轮仅完成诊断，尚未实现该干预。后续模型、真实缺陷和留出集扩展仍按主计划推进。
