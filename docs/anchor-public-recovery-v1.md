# 同一次恢复：锚点诊断与公开边界检查

2026-10-08。

## 结果

三个已知失败共享新的首轮补丁。冻结 Target/Controls：锚点组 2/3，联合组 2/3。

同时通过冻结评分与本轮公开边界检查：**1/3 → 2/3**。新增 ['more-split-empty']；丢失 []。

| 任务 | 仅锚点：状态 / 公开检查 | 联合：状态 / 公开检查 |
|---|---|---|
| more-falsy-exception | passed / 通过 | passed / 通过 |
| more-seekable-zero | invalid_patch / 失败 | invalid_patch / 失败 |
| more-split-empty | passed / 失败 | passed / 通过 |

## 实现与约束

上一轮仅纠正唯一匹配错误，空拆分补丁仍对 iter([]) 返回 [[]]。本轮把认证过的公开用例和旧源码失败观察加入同一次重交请求，同时处理编辑应用与行为边界。

空列表、空迭代器应无分组；非空输入 maxsplit=0 应保持单组。固定期望来自公开需求与 API 语义，先在旧源码/参考版本认证，再用于模型反馈。其他两项沿用假值异常和 maxlen=0 公开检查。参考源码仅供离线认证，不进入模型输入。

首轮提示、类范围检索证据、模型、输出限制和编辑器保持一致。两组共享新首轮及诊断，各有一次重交；联合组提供公开测试与观察并要求通过后保留。变化同时包含反馈和保留规则，不能把效果仅归于某句话。

每组最多两次请求，累计 15,000 Token。没有追加第三次修复。唯一匹配、范围、源码版本检查保留，补丁在副本应用及编译。公开验证失败或出错会恢复首轮快照。

实际调用与用量：`{'model_calls': 9, 'tokens': 37734, 'missing_usage_calls': 0}`。每列累计含共享首轮，不能直接相加；实际账目只计一次首轮，再计两种重交。没有分别测量策略耗时，不宣称提速。

## 范围与决策

决策：`known_case_gain_requires_broader_validation`。三项均为已看过的困难任务，不能据此更新 50 项总体通过率或宣称新留出提升。默认 Agent/API 未接入；冻结评分与新增公开检查分列，不改历史结果。

独立手写缺陷与正常行为检查仍可能遗漏边界，不等于完整上游测试。下一步优先扩大已冻结开发集验证，避免继续围绕单例追加提示。

工程验收：`{'targeted_pytest': {'passed': 14}, 'windows_pytest': {'passed': 1239, 'skipped': 2, 'seconds': 194.21}, 'ruff': 'passed', 'model_calls': 9, 'tokens': 37734, 'linux_docker_http': 'not rerun', 'deepseek': 'not used'}`。

- [流程实现](experiments/anchor_public_recovery_v1.py)、[反馈与回滚测试](../tests/test_anchor_public_recovery_v1.py)。
- [完整结果](anchor-public-recovery-v1.json)、[上轮锚点恢复](exact-anchor-recovery-v1.md)。
- 原始运行 `D:\project_other\CoreCoder\.tmp\real-defects\anchor-public-recovery-v1\experiment.json`；SHA256 `188a2340766b61b987b0792aa79bb4d877bc28573c41b2f8ec148d1daaf52d84`。
