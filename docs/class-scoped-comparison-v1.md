# 类范围检索：一轮完整优化对照

2026-10-08。

## 结果与决策

开发集独立通过：基线 **12/30**，候选 **14/30**。新增成功 3 项、丢失成功 1 项。

开发正常行为检查通过：基线 29/30，候选 29/30。

新增 Controls 失败：itsdangerous-none-salt；消除旧 Controls 失败：toolz-interpose-empty。回归总数不增加不等于逐项没有新回归。

开发门槛：通过；留出状态：all_20_pairs_completed。最终决策：positive_development_and_heldout_pairing_optional_policy。

若未通过开发门槛，停止本轮候选并保留旧方案；没有为得到更好的结果修改候选或挑选任务重跑。若留出未验证收益，也不替换默认流程。

## 方法来源与实际改动

参考 [Agentless 分层定位](https://github.com/OpenAutoCoder/Agentless)和 [Aider 结构索引](https://aider.chat/docs/repomap.html)，新增 AST 限定符号与唯一类范围排序。完整调研、区别和事前停止条件见 [调研记录](class-scoped-research-v1.md)。

候选优先明确函数引用、被提到的唯一类构造方法及该类其他方法，再按加入限定名的 BM25 排序。可编辑证据仍是原始完整函数。

构造方法优先可能占用片段预算并挤掉重要方法；没有动态调用图、继承解析或语义状态推断。零分普通候选排在最后按源码顺序排序，相关候选不足时仍可能填入无关片段。

## 同一任务池通过数

| 范围 | 基线 | 候选 |
|---|---:|---:|
| 开发 | 12/30 | 14/30 |
| 留出 | 9/20 | 11/20 |
| 全部 | 21/50 | 25/50 |

## 固定对照

- 全部 30 个开发任务逐项运行新基线和新候选；每个任务独立工作区，交替两组执行顺序。
- 同一冻结 Qwen digest、Prompt、Worker、6000 原文字符、最多五个函数、单次调用、15000 Token、输出 2048 Token。
- 私有 Target/Controls 和 reference 不进入检索或模型输入；只作最终评分。所有 50 项证据在首次调用前冻结。
- 门槛事前固定为开发至少新增净通过 2、Controls 失败数不增加；通过后才运行 20 个留出新配对。
- 本轮是一个组合检索政策的对照，不能将收益分别归因于限定名、显式函数排序或构造函数优先。

两组都把检索分数、排序位置和来源标记随原文送入冻结 Worker；这些元数据也会随政策改变。源码正文相同的任务仍可能生成不同补丁，不能将每个差异都解释为新增源码的收益。

开发诊断：interpose 将已有函数提前后通过；chunked-negative 补入之前缺失的 chunked；range-equality 补入 __hash__ 后通过。bucket 已展示五个方法仍只把 iter(cache) 改为 iter(cache.keys())，未消除虚构键。combination-size 两组函数正文及顺序相同，候选遗漏空池边界，出现 ValueError；检索元数据不同。这些是轨迹观察，不是各机制的独立因果证据。

## 成本

| 范围 | 方案 | 调用 | Token | Worker 秒 |
|---|---|---:|---:|---:|
| development | baseline | 30 | 83175 | 303.5351 |
| development | class-scoped | 30 | 83110 | 340.8037 |
| heldout | baseline | 20 | 62803 | 329.1022 |
| heldout | class-scoped | 20 | 60083 | 287.5259 |

Worker 时间不包含检索、复制和独立评分，受模型加载与缓存影响；Token 为返回用量，不是实际云费用。没有调用 DeepSeek。

## 逐项配对结果

| split | 任务 | 基线 | 候选 |
|---|---|---|---|
| development | boltons-backoff-constant | target_failed | target_failed |
| development | boltons-chunked-bytes | target_failed | target_failed |
| development | boltons-split-zero | passed | passed |
| development | click-echo-empty-bytes | passed | passed |
| development | click-flag-default-map | target_failed | target_failed |
| development | click-flag-envvar | target_failed | target_failed |
| development | click-help-eagerness | target_failed | target_failed |
| development | click-invoke-missing | passed | passed |
| development | click-prompt-suffix | target_failed | target_failed |
| development | click-resource-exception | target_failed | target_failed |
| development | click-shared-default | target_failed | target_failed |
| development | click-style-color-validation | passed | passed |
| development | click-usage-empty | target_failed | target_failed |
| development | itsdangerous-future-age | passed | passed |
| development | itsdangerous-malformed-time | passed | passed |
| development | itsdangerous-none-salt | target_failed | control_regression |
| development | more-bucket-missing-key | target_failed | target_failed |
| development | more-chunked-negative | target_failed | passed |
| development | more-combination-size | passed | target_failed |
| development | more-ichunked-zero | passed | passed |
| development | more-permutation-exception | target_failed | target_failed |
| development | more-predicate-sentinel | target_failed | target_failed |
| development | more-range-equality | target_failed | passed |
| development | more-range-membership | target_failed | target_failed |
| development | more-sliced-negative | passed | passed |
| development | more-windowed-zero | passed | passed |
| development | toolz-accumulate-empty | passed | passed |
| development | toolz-getter-empty | passed | passed |
| development | toolz-interpose-empty | control_regression | passed |
| development | toolz-join-unmatched | target_failed | target_failed |
| heldout | boltons-backoff-zero | output_truncated | output_truncated |
| heldout | boltons-remap-set | target_failed | target_failed |
| heldout | boltons-repeat-equality | passed | passed |
| heldout | boltons-xfrange-descending | passed | passed |
| heldout | more-batch-count | passed | passed |
| heldout | more-broadcast-single-use | target_failed | target_failed |
| heldout | more-combination-index | passed | passed |
| heldout | more-falsy-exception | invalid_patch | invalid_patch |
| heldout | more-gray-partial-repeat | control_regression | control_regression |
| heldout | more-interleave-empty | passed | passed |
| heldout | more-last-typeerror | passed | target_failed |
| heldout | more-negative-range-slice | target_failed | passed |
| heldout | more-product-repeat | control_regression | passed |
| heldout | more-reverse-empty-range | invalid_patch | passed |
| heldout | more-reversed-values | target_failed | target_failed |
| heldout | more-seekable-zero | target_failed | invalid_patch |
| heldout | more-split-empty | invalid_patch | invalid_patch |
| heldout | more-value-chain-error | passed | passed |
| heldout | toolz-merge-mapping | passed | passed |
| heldout | toolz-partition-length | passed | passed |

## 开发集按缺陷类型

| 类型 | 任务数 | 基线通过 | 候选通过 |
|---|---:|---:|---:|
| callback_and_exception | 4 | 1 | 1 |
| defaults_and_boundaries | 10 | 4 | 5 |
| numeric_consistency | 4 | 1 | 2 |
| parameter_validation | 6 | 5 | 5 |
| state_and_consumption | 3 | 0 | 0 |
| type_and_representation | 3 | 1 | 1 |

## 局限与下一步

每组每任务一次，开发任务已查看过，相关函数和仓库跨 split；不是盲测或 SWE-bench，也不能证明通用收益。目标未通过不直接等于检索错误。

独立评分同时检查目标行为、正常行为与修改范围。后续策略必须作为新版本和新对照，不能覆盖本轮失败。默认 Agent、API 和冻结旧版结果均未修改。

Windows 全量 1,206 passed、2 skipped；本轮专项 8 passed；新增模块 Ruff 通过。没有重跑 Linux、Docker 或 HTTP。

[机器可读配对结果](class-scoped-comparison-v1.json) · [上一版 50 项基线](expanded-baseline-v2.md)
