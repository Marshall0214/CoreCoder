# 原文恢复策略：30 项开发集扩大验证

2026-10-08。

## 结果与决策

独立 Target/Controls 通过 **14/30 → 14/30**；新增 []，丢失 []。

正常行为 Controls **29/30 → 29/30**。实际恢复触发 **0/30**，触发任务 []。

决策：`no_trigger_coverage_stop_rollout`；推广门槛通过：`False`。

恢复只针对首轮原文唯一匹配事务拒绝。若首轮补丁能应用，即使后来语义测试失败，也不会调用这条恢复分支。没有触发时，两组共享完全相同的候选；不能把其通过任务数归功于恢复策略，也不能证明该策略解决了语义失败。

## 实施与固定条件

完整重跑既有 30 项开发任务，没有按失败结果挑子集，也没有继续逐题改提示。沿用上轮联合恢复适配器；两个策略共享新首轮，分别为只含锚点诊断与同时包含认证公开检查的重交。

保留同一 Qwen digest、首轮提示、类范围检索、五个完整函数/6000 字符证据限制。每组最多两次调用、累计 15,000 Token；未触发任务只调用一次。唯一匹配、范围和源码版本保护保持不变，默认 Agent/API 未改变。

全部 30 项公开检查使用此前认证的固定用例，不重写预期；worker 只收到描述、原始证据和公开检查。参考版本和私有评分未进入模型输入，Target/Controls 在 worker 结束后独立执行。已见过的开发集不是新盲测；本轮不再运行留出。

实际调用账目：`{'model_calls': 30, 'tokens': 83110, 'missing_usage_calls': 0}`。共享首轮只计一次，不把两组累计 Token 相加。两组进程耗时来自同一 worker，不用于宣称速度提升。

首轮状态：`{'completed': 30}`。联合组结果分类：`{'target_failed': 15, 'passed': 14, 'target_and_control_failed': 1}`。分类仅描述可观察失败，不直接归因于检索或模型推理。

## 逐项核查

| 任务 | 恢复触发 | 联合组结果 | 公开检查 |
|---|---|---|---|
| click-usage-empty | False | target_failed | 失败 |
| click-echo-empty-bytes | False | passed | 通过 |
| click-style-color-validation | False | passed | 通过 |
| itsdangerous-none-salt | False | target_and_control_failed | 失败 |
| itsdangerous-future-age | False | passed | 通过 |
| itsdangerous-malformed-time | False | passed | 通过 |
| click-help-eagerness | False | target_failed | 失败 |
| click-flag-default-map | False | target_failed | 失败 |
| click-resource-exception | False | target_failed | 失败 |
| click-flag-envvar | False | target_failed | 失败 |
| click-prompt-suffix | False | target_failed | 失败 |
| click-invoke-missing | False | passed | 通过 |
| click-shared-default | False | target_failed | 失败 |
| toolz-interpose-empty | False | passed | 通过 |
| toolz-accumulate-empty | False | passed | 通过 |
| toolz-join-unmatched | False | target_failed | 失败 |
| toolz-getter-empty | False | passed | 通过 |
| boltons-backoff-constant | False | target_failed | 失败 |
| boltons-split-zero | False | passed | 通过 |
| boltons-chunked-bytes | False | target_failed | 失败 |
| more-ichunked-zero | False | passed | 通过 |
| more-bucket-missing-key | False | target_failed | 失败 |
| more-range-membership | False | target_failed | 失败 |
| more-chunked-negative | False | passed | 通过 |
| more-range-equality | False | passed | 通过 |
| more-sliced-negative | False | passed | 通过 |
| more-windowed-zero | False | passed | 通过 |
| more-predicate-sentinel | False | target_failed | 失败 |
| more-combination-size | False | target_failed | 失败 |
| more-permutation-exception | False | target_failed | 失败 |

## 下一项核心问题

当补丁可应用但行为错误时，需要进入公开缺陷与正常行为反馈流程，而不是再扩展锚点诊断。此前独立开发配对的公开反馈已达到 14/30 → 17/30；本轮未执行该语义纠正分支，不能拿这里的比例与 17/30 直接比较策略优劣。

停止把局部原文恢复当作总体优化，保留为编辑拒绝时的可选实验路径。后续优先分析已应用的错误补丁及公开反馈未修好的案例，并选定一个流程级干预后做新配对，不继续围绕三个已知单例堆提示。

手写 Target/Controls 和公开检查不等于完整上游测试；没有总体增益时不接入默认流程。旧 50 项统计和留出报告不改写。

工程验收：`{'targeted_pytest': {'passed': 20}, 'windows_pytest': {'passed': 1245, 'skipped': 2, 'seconds': 207.2}, 'ruff': 'passed', 'model_usage': {'model_calls': 30, 'tokens': 83110, 'missing_usage_calls': 0}, 'linux_docker_http': 'not rerun', 'deepseek': 'not used'}`。

- [完整逐项结果](anchor-public-development-v1.json)、[扩大验证执行器](experiments/anchor_public_development_v1.py)。
- [覆盖与推广门槛测试](../tests/test_anchor_public_development_v1.py)、[三项已知诊断](anchor-public-recovery-v1.md)。
- [此前语义反馈配对](public-feedback-v2.md)。
- 原始运行 `D:\project_other\CoreCoder\.tmp\real-defects\anchor-public-development-v1\experiment.json`；SHA256 `d8a21d9ed57163905bff40c251558c11c40879e394bddadb12f8a59848ee2ee6`。
