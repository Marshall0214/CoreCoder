# 原文唯一匹配失败：一次事务恢复

2026-10-08。

## 实际结果

三项已知失败的新首轮均为 invalid_patch；一次恢复后 **2/3** 补丁可应用，冻结 Target/Controls 计分 **0/3 → 2/3**。

**但空拆分补丁仍不能正确处理空迭代器。**额外公开核查失败，因此不能把两项计分成功都宣称为正确修复；当前恢复流程不接入默认 Agent/API。

| 任务 | 首轮 | 恢复后 | 解释 |
|---|---|---|---|
| more-falsy-exception | 无效补丁 | 冻结验收通过 | 两处重复原文得到区分，自定义假值异常按 None 判断，目标与 Controls 通过 |
| more-seekable-zero | 无效补丁 | 仍无效 | 第二轮仍未满足唯一匹配 |
| more-split-empty | 无效补丁 | 计分通过，额外核查失败 | 编辑锚点恢复成功，但 if iterable 未识别空迭代器 |

## 实现了什么

在首轮事务拒绝后，仅在内存中按顺序重放候选，定位首个不唯一锚点。反馈给模型该编辑序号、当前匹配次数、原始匹配次数、已展示的函数归属和完整被拒绝事务，再要求针对未改动源码重交完整补丁。

没有自动替换、模糊匹配或按行号修改。仍要求原文在整文件唯一出现、来源已在上下文展示、文件版本一致、编辑范围合法，并在副本中应用和编译后才写回。先前可成功的前缀也不会从失败事务中提交。

同一 Qwen、原类范围证据最多五个完整函数/6000 字符、最多两次调用，共享 15,000 Token。第二轮只反馈编辑器拒绝原因，没有参考源码、私有测试或行为评分。两组共享新首轮，费用按累计候选计数。

实际 6 次调用、22320 Token；首轮占 3 次、9028 Token。两列不能相加。未分开测量首轮/恢复耗时，不据此宣称提速。

## 额外核查与范围

split_before、split_after、split_when 对 iter([])、maxsplit=0 应返回 []；补丁返回 [[]]。见证在旧源码失败、参考版本通过，正常非空迭代器仍通过。该见证是在补丁审阅后新增，不改写冻结计分，也没有追加模型尝试。

这些是按既有失败选择的三个已看过任务，证明事务恢复在本组能解决两项应用失败，不能估计 50 项总体效果或宣称新的留出提升。测试通过仅限约定手写评分，不是完整上游套件。

## 收尾与下一步

保留事务恢复为实验适配器；下一步优先把空迭代器这一真实失败反馈给已恢复的候选，验证编辑恢复与行为修正能否在同一预算内配合，避免只解决格式便结束任务。不继续扩任务、服务或无上限重试。

验收：`{'targeted_pytest': {'passed': 7}, 'windows_pytest': {'passed': 1232, 'skipped': 2, 'seconds': 193.01}, 'ruff': 'passed', 'model_calls': 6, 'tokens': 22320, 'application_recovered': 2, 'frozen_grader_passed': 2, 'posthoc_empty_iterator_candidate_passed': False, 'linux_docker_http': 'not rerun', 'deepseek': 'not used'}`。

- [恢复实现](experiments/exact_anchor_recovery_v1.py)、[诊断和事务测试](../tests/test_exact_anchor_recovery_v1.py)。
- [运行与额外核查 JSON](exact-anchor-recovery-v1.json)、[此前固定预期结论](fixed-product-checks-v1.md)。
- 原始运行 `D:\project_other\CoreCoder\.tmp\real-defects\exact-anchor-recovery-v1\experiment.json`；SHA256 `5cc27132bbb4071b75bc9086abfda877db66b143265dd981f117beaa7cdabf41`。
