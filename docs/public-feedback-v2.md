# 公开复现检查与一次修正：30 项开发集完整对照

2026-10-08。

## 做了什么与结果

首轮仍按类范围检索生成补丁。随后运行事前认证的公开复现和正常行为检查；失败时，把检查代码、实际失败输出和当前完整函数交给模型，最多修正一次。修正后的两组公开检查全部通过才保留，否则回退首轮结果。私有 Target/Controls 在模型结束后独立评分。

独立修复通过 **14/30 → 17/30**。新增成功 3 项、丢失成功 0 项。
正常行为 Controls 通过 **29/30 → 29/30**。

开发门槛：通过。决策：`freeze_for_separate_heldout_validation`。本轮没有运行留出集，没有接入默认 Agent/API。

## 检查如何认证

- 为全部固定 30 个开发任务手写公开描述示例；模型未自动生成测试。
- 旧源码：Reproduce 必须有实际失败，Preserve 必须通过；参考版本：两组必须通过。每组至少运行一个测试，无跳过、超时或发现失败。
- 在独立 Python 进程导入指定源码，检查来源和执行前后源码/测试哈希；每组 15 秒超时。
- 认证完成并冻结全部描述、检查和检索结果后才调用模型。

编写者已查看此前实验结果，这不是盲测。认证时曾根据公开 API 和参考版本的检查结果修正四项错误预期/导入，参考源码和私有测试代码未进入修复模型。参考认证仍可能使公开检查贴近已知修复，不能当作完全独立的测试生成研究。

## 固定条件与成本口径

- 同一 Qwen digest、不启用思考、temperature=0、top_p=1；单次输出最多 2048 Token。
- 累计 15,000 Token、上下文 16,000、最多两次调用；当前证据仍最多五个完整函数、6000 原文字符，无新增工具。
- 两组共享同一个新首轮结果：single 评分首轮快照，public-feedback 评分经过修正/回退的最终副本。不是两组各自独立采样。
- 第一次提示与原类范围策略一致；第二次只有公开检查、公开运行观察和刷新的当前种子函数，无参考答案/私有评分反馈。

| 指标 | 单次首轮 | 包含一次可选修正 |
|---|---:|---:|
| 调用 | 30 | 46 |
| Token | 83110 | 135662 |
| 执行秒 | 343.596 | 603.0468 |

实际合计是 **46 次 / 135662 Token**；候选列已经包含首轮，不能把两列相加。单次时间为首轮模型和应用耗时，候选时间还包含 Worker 启动和公开检查；两列不适合当作纯模型延迟对照。独立私有评分不计入这里。

单次组与反馈组拥有不同的调用机会；本轮评估的是额外修正、公开反馈、当前证据与保留规则的组合收益，未加入同样两次但不提供反馈的消融组，不能单独证明测试反馈的因果收益。

## 失败与正常行为保持

反馈尝试 16，保留修正 3。修正阶段状态：`{"completed": 15, "output_truncated": 1}`。

公开检查通过但私有验收仍失败：无。公开检查通过不能替代独立评分。

新增 Controls 失败：无；消除旧 Controls 失败：无。

新增修复：boltons-chunked-bytes, more-bucket-missing-key, more-combination-size。丢失修复：无。

## 按缺陷类型

| 类型 | 任务数 | 首轮通过 | 最终通过 |
|---|---:|---:|---:|
| callback_and_exception | 4 | 1 | 1 |
| defaults_and_boundaries | 10 | 5 | 5 |
| numeric_consistency | 4 | 2 | 2 |
| parameter_validation | 6 | 5 | 6 |
| state_and_consumption | 3 | 0 | 1 |
| type_and_representation | 3 | 1 | 2 |

## 逐项独立评分

| 任务 | 首轮 | 最终 |
|---|---|---|
| click-usage-empty | target_failed | target_failed |
| click-echo-empty-bytes | passed | passed |
| click-style-color-validation | passed | passed |
| itsdangerous-none-salt | control_regression | control_regression |
| itsdangerous-future-age | passed | passed |
| itsdangerous-malformed-time | passed | passed |
| click-help-eagerness | target_failed | target_failed |
| click-flag-default-map | target_failed | target_failed |
| click-resource-exception | target_failed | target_failed |
| click-flag-envvar | target_failed | target_failed |
| click-prompt-suffix | target_failed | target_failed |
| click-invoke-missing | passed | passed |
| click-shared-default | target_failed | target_failed |
| toolz-interpose-empty | passed | passed |
| toolz-accumulate-empty | passed | passed |
| toolz-join-unmatched | target_failed | target_failed |
| toolz-getter-empty | passed | passed |
| boltons-backoff-constant | target_failed | target_failed |
| boltons-split-zero | passed | passed |
| boltons-chunked-bytes | target_failed | passed |
| more-ichunked-zero | passed | passed |
| more-bucket-missing-key | target_failed | passed |
| more-range-membership | target_failed | target_failed |
| more-chunked-negative | passed | passed |
| more-range-equality | passed | passed |
| more-sliced-negative | passed | passed |
| more-windowed-zero | passed | passed |
| more-predicate-sentinel | target_failed | target_failed |
| more-combination-size | target_failed | passed |
| more-permutation-exception | target_failed | target_failed |

## 新增成功的具体变化

- 字节分块：首轮用 b"".join 拼接整数，公开执行报 TypeError；第二轮改为 bytes(chunk)，独立目标与正常行为检查通过。
- bucket：首轮仅将 iter(cache) 改为 iter(cache.keys())，行为未变；第二轮排除空缓存键，独立验收通过。没有验证完整上游套件。
- 组合边界：首轮删除 r 大于池长的错误限制，但空池、r=0 仍失败；反馈后增加空池边界分支，独立验收通过。

## 工程验收

验收记录：`{"public_certification": {"tasks": 30, "certified": 30, "model_calls": 0}, "targeted_pytest": {"passed": 11}, "windows_pytest": {"passed": 1217, "skipped": 2, "seconds": 204.26}, "ruff": "passed", "linux_docker_http": "not rerun"}`。没有重跑 Linux/Docker/HTTP，没有使用 DeepSeek；核心 Agent 与默认服务没有修改。

## 后续与证据

达到事前门槛（净新增至少 2、Controls 通过数不下降）后，下一轮先冻结留出公开检查与相同策略再单独验证。否则收尾本策略，依据剩余失败分类选择下一项核心干预，不扩大重试和提示字段。

任务池是小型 Python 库历史缺陷，多数为单文件；开发集收益不代表仓库级或跨文件泛化。既有 50 项检索对照仍保持原报告，不能把本轮开发结果拼入旧留出结果报告一个新总体成功率。

- [实现](experiments/public_feedback_v2.py)、[公开检查](experiments/public_feedback_cases_v1.py)、[流程测试](../tests/test_public_feedback_v2.py)。
- [完整逐项 JSON](public-feedback-v2.json)、[前一轮类范围对照](class-scoped-comparison-v1.md)。
- 原始运行：`.tmp\real-defects\public-feedback-v2-development\experiment.json`；SHA256：`f4fb217c9b892f59fd7ee68111906f1b3aa95a9e104c78a806129676b11c6c1c`。
