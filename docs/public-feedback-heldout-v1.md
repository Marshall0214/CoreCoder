# 公开检查反馈：冻结策略的 20 项留出验证

2026-10-08。

## 结果与决定

冻结 Target/Controls 计分通过 **11/20 → 13/20**；新增计分成功 2、丢失计分成功 0。

私有 Controls 通过 **19/20 → 20/20**。新增 Controls 失败：无。

事前留出门槛：通过；决定：`do_not_adopt_known_public_regression`。默认 Agent/API 未改动。

**额外公开核查发现 more-gray-partial-repeat 的正常行为回归，评分漏检，因此不采用当前策略。**具体反例与检查缺口见下方补丁审计。

门槛是全部 20 个配对完成、净新增成功为正且零新增 Controls 失败。通过允许继续审阅，不自动接入；发现已知行为回归仍阻止采用。失败则停止扩大该策略，不挑题重跑或更改 Prompt。

## 固定策略

直接运行前一轮 `public_feedback_v2.worker`，没有复制或修改修复逻辑：首轮按类范围检索生成补丁；公开 Reproduce/Preserve 失败后最多一次修正，两轮共享 15,000 Token；修正必须通过两组公开检查才保留，否则保留首轮。

- 同一 Qwen digest、无思考、temperature=0、top_p=1，输出最多 2048 Token，上下文 16,000；无新增工具。
- 证据最多五个完整函数、6000 原文字符；修正仅刷新原种子函数，不扩展检索。
- 全部 20 项公开检查与检索结果在第一次调用前冻结，并核对导入的 Provider、预算、解析和源码模块哈希。
- 模型不接收参考源码/私有评分；完成模型调用后，才在干净评分副本运行 Target/Controls。
- 两组共享同一次新首轮：single 评分首轮快照，public-feedback 评分最终副本，节省重复运行。

## 公开检查与验证边界

20 项检查均为手写公开描述/API 示例。认证要求旧源码 Reproduce 有实际失败、Preserve 通过，参考版本两组通过；检查来源、非空执行、无跳过、超时和源码/测试哈希。认证阶段未调用模型。

认证时修正了组合索引的触发示例和 xfrange 参数顺序，不基于本轮模型结果调试。参考版本仅作离线认证；检查代码不是自动生成的，也不是独立盲测产物。

这些任务先前已用于类范围检索实验，作者也看过相关结果，部分缺陷家族跨开发/留出共享。因此这里只验证新增反馈策略在固定留出任务上的表现，不能宣称新的仓库级盲测或排除训练污染。评分也是手写 Target/Controls，没有运行完整上游套件。

## 收益与成本

| 指标 | 单次首轮 | 包含一次可选修正 |
|---|---:|---:|
| 独立通过 | 11/20 | 13/20 |
| 调用 | 20 | 25 |
| Token | 60083 | 76235 |
| 执行秒 | 281.362 | 369.3999 |

实际总消耗 **25 次 / 76235 Token**；额外 16152 Token。候选包含首轮，不能相加两列。

首轮时间是首次请求及应用，候选还包含 Worker 启动和公开检查，均不含独立私有评分；时间不作为纯模型延迟比较。反馈组拥有额外一次调用机会，尚无等调用次数的无反馈消融，不能单独归因于测试内容。

反馈尝试 5；保留修正 2；阶段状态：`{"invalid_patch": 1, "completed": 4}`。

公开检查通过但私有验收仍失败：无。公开检查不能替代独立评分。

新增成功：more-gray-partial-repeat, more-last-typeerror。

丢失成功：无。消除旧 Controls 失败：more-gray-partial-repeat。

## 分类结果

| 缺陷类型 | 任务数 | 首轮 | 最终 |
|---|---:|---:|---:|
| callback_and_exception | 3 | 1 | 2 |
| defaults_and_boundaries | 4 | 2 | 2 |
| numeric_consistency | 5 | 4 | 4 |
| parameter_validation | 2 | 2 | 2 |
| state_and_consumption | 4 | 1 | 2 |
| type_and_representation | 2 | 1 | 1 |

## 逐项独立评分

| 任务 | 首轮 | 最终 |
|---|---|---|
| boltons-remap-set | target_failed | target_failed |
| more-falsy-exception | invalid_patch | invalid_patch |
| more-batch-count | passed | passed |
| more-seekable-zero | invalid_patch | invalid_patch |
| more-combination-index | passed | passed |
| more-split-empty | invalid_patch | invalid_patch |
| more-value-chain-error | passed | passed |
| more-interleave-empty | passed | passed |
| more-reverse-empty-range | passed | passed |
| more-negative-range-slice | passed | passed |
| more-product-repeat | passed | passed |
| more-gray-partial-repeat | control_regression | passed |
| more-reversed-values | target_failed | target_failed |
| more-broadcast-single-use | target_failed | target_failed |
| more-last-typeerror | target_failed | passed |
| boltons-xfrange-descending | passed | passed |
| boltons-backoff-zero | output_truncated | output_truncated |
| boltons-repeat-equality | passed | passed |
| toolz-partition-length | passed | passed |
| toolz-merge-mapping | passed | passed |

## 工程验收

`{"public_certification": {"tasks": 20, "certified": 20, "model_calls": 0}, "targeted_pytest": {"passed": 17}, "windows_pytest": {"passed": 1223, "skipped": 2, "seconds": 204.18}, "ruff": "passed", "posthoc_public_witness": {"task": "more-gray-partial-repeat", "original_preserved": true, "candidate_preserved": false, "model_calls": 0}, "linux_docker_http": "not rerun", "deepseek": "not used"}`。

## 补丁审计发现的漏检回归

**计分门槛通过，但发现已知正常行为回归，因此不采用当前策略。**原始 11/20 → 13/20 与逐项计分记录保留，不事后改写评分或挑选重跑。

新增计分成功 more-gray-partial-repeat 中，模型把 `tuple(map(iter, iterables * repeat))` 改成 `tuple(map(iter, iterables)) * repeat`，多个位置因此共享迭代器。正常序列 `partial_product([2,3],[8,9], repeat=2)` 的首项从 `(2,8,2,8)` 变成 `(2,8,3,9)`；零模型调用的独立公开见证在原始源码通过、最终补丁失败。

公开检查用“当前函数在普通序列上的结果”与“当前函数在单次迭代器上的结果”作相等比较；补丁可以同时改变两边，使错误输出一致。私有 Target/Controls 也漏掉了这项原有行为。因此两项新增计分成功中至少一项不能当作正确修复，不能宣称新增两项均完整满足需求。

该见证是在本轮完成后按补丁审阅新增的单项核查，不是事前冻结评分，也不是全量回归覆盖率。没有参考修复或私有答案进入见证，没有修改候选或再次调用模型。

审计来源 `.tmp\real-defects\public-feedback-heldout-v1-audit\audit.json`；SHA256 `4f29608d839c46e71c8d4757670ca4f329aa9e6d1f99716ae82bf11d4ac4d2d7`。见 [独立公开核查](experiments/public_feedback_heldout_audit_v1.py)。

## 后续与证据

保留 [开发集 14/30 → 17/30 的原报告](public-feedback-v2.md)。本次使用同一冻结策略，但公开检查的编写批次与执行时间不同；两阶段分开报告，未重跑全部 50 项同一批次，不用拼接总体比例代替开发/留出结果。

下一步先修复检查中会随候选变化的预期：从描述和修复前源码的合法行为冻结预期，认证后不随补丁重新计算；把迭代器共享见证加入新版本检查。旧报告保持不变，再判断如何有限修正。当前流程不接入默认服务。

- [留出执行器](experiments/public_feedback_heldout_v1.py)、[公开检查](experiments/public_feedback_heldout_cases_v1.py)、[冻结 Worker](experiments/public_feedback_v2.py)。
- [流程测试](../tests/test_public_feedback_heldout_v1.py)、[完整结果 JSON](public-feedback-heldout-v1.json)。
- 原始运行 `.tmp\real-defects\public-feedback-heldout-v1\experiment.json`；SHA256 `aed4a446c9d63ee0ba3f82b5e76776b1c15b9828ca53c1d16bcde37cf911c1fe`。
