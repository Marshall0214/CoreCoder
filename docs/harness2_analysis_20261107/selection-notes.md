# Harness² 50 项：候选与交付选择审计

本审计只读取已保存的文件，未调用模型、未运行测试、未重新执行 selector，也未修改运行时。可复算脚本为 `selection_analysis.py`，输出为 `selection-analysis.json`。所有独立结果均来自本轮交付后的原有评分，不利用它们回头选优或宣称新的通过率。

## 1. 交付策略不是质量投票

冻结源码 `D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/implementation/integrations/harness2_selection.py`：

- 第 10 行固定优先级为 `agg1 > base1 > inv1 > dom1`。
- 第 41 行要求反馈终态 `ready_for_review`、公开 accepted、原始输入未变。
- 第 47–58 行检查与最终补丁哈希匹配的 Reproduce/Preserve 成功收据。
- 第 64 行选择优先级最高的公开验收候选。
- 第 66–67 行规定：所有候选都未公开 accepted 时，仍交付没有完整性错误的官方 agg1 失败产物，之后独立评分。

因此“交付 agg1”不等于它比其他候选更优，也不等于其公开测试通过。实际交付 47 项 agg1、2 项 base1、1 项 dom1；其中 25 项交付物公开 accepted，另 25 项没有通过公开准入。

## 2. 公开验收和独立评分并不等价

| 交付物公开状态 | 独立通过 | 独立未通过 |
|---|---:|---:|
| accepted | 23 | 2 |
| 未 accepted | 2 | 23 |

公开 accepted 但独立未通过：

1. `click-flag-envvar`：交付 dom1。公开测试仅断言 false/0/no 不产生 UPPER，没有要求准确的关闭值。公开源码 `D:/project_other/CoreCoder/.tmp/real-defects/system-comparison-v1-rerun/admission/click-flag-envvar/public/test_admission.py:15` 使用 `assertNotEqual(..., repr('UPPER'))`，因此返回 None 也被接受。独立 Target 对关闭值有精确断言，出现 `None != 'False'`，共 6 个 subtest 失败；Controls 通过。现有补丁的分支还把不匹配字符串映射成 None。应诊断为公开契约覆盖不足，不应把这次 accepted 当作完整修复证明。
2. `click-prompt-suffix`：交付 agg1，仅修改 `prompt()` 的空后缀空格；公开测试只覆盖 `prompt()`，没有 `confirm()`。独立 Target 的 `confirm()` 分支仍输出 `Proceed yes`，要求为 `Proceedyes`。公开源码 `D:/project_other/CoreCoder/.tmp/real-defects/system-comparison-v1-rerun/admission/click-prompt-suffix/public/test_admission.py:10`；独立日志位于本任务 agg1 的 `grading/grading-logs/Target.stderr.txt`。base1 与交付 agg1 最终工作区哈希相同，换选 base1 不能解决这个覆盖缺口。

公开未 accepted 但独立通过：

- `itsdangerous-malformed-time`：公开验证不是判定补丁错误，而是在第一次修正后遭遇 `SandboxError: sandbox_invalid_result`，终态 validation_blocked；交付补丁独立通过。不能把这个例子称为公开测试的逻辑误拒绝。
- `more-combination-size`：公开 Reproduce 初始失败，随后 20 次修正均没有成功应用，最终补丁仍独立通过。应检查两套契约的差异，不能把独立结果反馈给 selector 来改变本轮分数。

## 3. 三次 fallback 的实际价值与边界

| 任务 | agg1 公开状态 | 交付 | 交付独立结果 |
|---|---|---|---|
| click-flag-envvar | 未通过，20 轮结束 | dom1 | 未通过 |
| boltons-backoff-constant | validation_blocked | base1 | 通过 |
| more-bucket-missing-key | validation_blocked | base1 | 通过 |

两项 base1 交付通过，说明保留已有候选具有实际工程价值。它们未交付的 agg1 没有被独立评分，不能严谨声称“没有 fallback 就一定会丢失两项独立成功”。backoff 的 base1、inv1、dom1 都公开 accepted；bucket 的 base1 与 inv1 补丁哈希一致。固定优先级选择了 base1，没有模型质量比较。

## 4. 旧 Harness² 的三个成功为什么没有保住

### itsdangerous-none-salt

四个候选均在第一次反馈补丁应用后遇到公开验证基础设施错误并停止；不是跑够 20 轮仍无法修复。agg1 补丁将 Serializer 默认 salt 改成 None，并在 None 时回退到 `itsdangerous.Serializer`；旧通过补丁保持构造默认值，仅将显式 None 回退到 `itsdangerous.Signer`。本轮独立 Target 和 Controls 均未通过：既未保持既有默认兼容性，也使用了不同的显式 None 语义。

证据：本任务 agg1 `feedback/rounds/001/validation/report.json:3` 为 blocked，第 45 行 `SandboxError: sandbox_invalid_result`；`grading/patch.diff` 和 `grading/grading-logs/Target.stderr.txt` 可直接对照。此处同时有补丁逻辑错误和反馈基础设施中断，不能只归因于指导词质量。

### boltons-split-zero

四个候选累计 80 次反馈，无一次成功改变最终工作区。终态均反馈轮数耗尽，最终哈希与原始输入相同；主要错误是 JSON 补丁 schema 不匹配、唯一锚点找不到。每次已有用量显示 prompt_tokens 为 32770，说明需要继续审计反馈输入边界与格式说明是否实际可见，当前只凭固定数字不能断定具体截断机制。

独立失败是原始 bug `[[[1, None, 3]]] != [[1, None, 3]]`，不是新补丁回归。旧成功补丁把 `yield [src]` 改成逐项收集后 `yield result`，当前没有任何已应用的新候选达到这个行为。

### more-negative-range-slice

base1 6 次反馈后 validation_blocked；inv1、dom1、agg1 的第一次反馈均约 480 秒后 local_provider_failed。当前 agg1 用 `slice.indices()` 归一化后仍将反向切片的 stop=-1 作为 `_get_by_index(-1)` 处理，使完整反向切片返回空序列。旧成功补丁通过 materialize 到列表再切片满足本组测试，但会改变大范围的时间/空间开销，不能据此称旧策略普遍更好。

证据：agg1 `feedback/report.json:2` 为 local_provider_failed，第 16 行耗时 480.047；`grading/patch.diff` 和 Target 日志显示 `[] != [6, 5, 4, 3, 2, 1, 0]`。

## 5. 唯一相对原始 Agent 的新增成功

`more-permutation-exception`：inv1、dom1、agg1 在探索阶段已经产生相同补丁，随后公开验证初次即通过，反馈次数均为 0；最终哈希同为 `0c08fded4ed5191053cc34b1f4636bdfc7cf3bbfb441686bb265b955410a63dc`。修改把 r>n 改为 IndexError，保留 r<0 的 ValueError。只有交付 agg1 被独立评分通过。

这支持“本次搜索产生了可通过的候选”，但不能支持“合成独有地改善了修复”或“反馈重试带来了本项成功”。base1 的修正受到验证基础设施中断，最终未 accepted。

## 6. 有无被选错、实际上更好的候选？

目前没有证据证明存在一个已独立通过的补丁被 selector 丢弃，导致本轮失败。所有 25 项独立失败中，仅上述两个 Click 任务存在公开 accepted 候选，且交付的已经是公开优先级最高者：

- prompt-suffix 另一个公开 accepted 的 base1 与交付 agg1 哈希完全相同，已知它不会改变结论。
- flag-envvar 公开 accepted 的 dom1 就是已交付者。
- 其余 23 项没有任何公开 accepted 候选。

补充只读哈希核对：对独立失败任务的所有当前候选，未发现与历史已成功交付补丁哈希相等者。未交付且内容不同的候选没有独立评分，正确状态是未知，不能擅自把它们计入修复收益。

四候选最后完全相同的任务有 14 项；交付候选与 base1 相同的有 31 项。其余内容不同不等于质量更好。相对 base1 内容不同且交付独立通过的有 6 项，base1 自身若不同则仍未独立评分，因此不能当作“提升 6 项”的对照结论。

## 7. 本轮结论和改进顺序

200 个反馈执行终态：87 个 ready_for_review，46 个 feedback_round_limit，36 个 validation_blocked，30 个 local_provider_failed，1 个 task_timeout。外层 50 个 PPC 全完成不能解释为内部验证和模型服务均无错误。

优先修复反馈公开验证的基础设施收据与协议，再处理模型请求长度/超时、补丁 schema 和锚点信息可见性；随后扩充可见契约的功能分支与精确输出断言，最后研究候选排序。直接增加 selector 自主性，当前没有足够证据显示能解决主要失败来源。

扩充公开测试时只依据任务的公开需求定义新版本契约，避免把已看过的独立答案直接变成原实验的公开指导；本轮独立分数保持 25/50，不因审计结果回填或改选。
