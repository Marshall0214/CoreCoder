# 当前策略完整 50 项修复评测

独立验收：历史 43/50 → 本轮 43/50。新增 5，丢失 5。
本轮 55 次模型调用，715,766 Token；相对历史 -9.46%。
审计：通过。

全部任务从原始源码重新生成候选，没有复用历史回答。原模型别名、预算及独立评分保持；当前检索应用于全部任务，新增公开契约仅应用于 envvar。已知任务池、单轮历史对比，不能独立归因算法收益，也不是盲测。

| 仓库 | 数量 | 历史通过 | 本轮通过 |
| --- | ---: | ---: | ---: |
| boltons | 7 | 6 | 7 |
| click | 10 | 5 | 6 |
| itsdangerous | 3 | 3 | 3 |
| more_itertools | 24 | 23 | 21 |
| toolz | 6 | 6 | 6 |

新增成功：click-help-eagerness, click-flag-default-map, click-flag-envvar, click-prompt-suffix, boltons-remap-set
历史成功丢失：click-usage-empty, click-resource-exception, click-invoke-missing, more-reverse-empty-range, more-range-equality

失败分类（截断优先；细节保留最终状态和独立分组）：

- public_validation_failed: 3
- output_truncated: 4

| 任务 | 历史 | 本轮 | 结果分类 | Token |
| --- | --- | --- | --- | ---: |
| click-usage-empty | 1 | 0 | public_validation_failed | 11720 |
| click-echo-empty-bytes | 1 | 1 | passed | 7398 |
| click-style-color-validation | 1 | 1 | passed | 16729 |
| itsdangerous-none-salt | 1 | 1 | passed | 22721 |
| itsdangerous-future-age | 1 | 1 | passed | 7723 |
| itsdangerous-malformed-time | 1 | 1 | passed | 9507 |
| click-help-eagerness | 0 | 1 | passed | 15437 |
| click-flag-default-map | 0 | 1 | passed | 3549 |
| click-resource-exception | 1 | 0 | public_validation_failed | 52145 |
| click-flag-envvar | 0 | 1 | passed | 49265 |
| click-prompt-suffix | 0 | 1 | passed | 7442 |
| click-invoke-missing | 1 | 0 | public_validation_failed | 40154 |
| click-shared-default | 0 | 0 | output_truncated | 59860 |
| toolz-interpose-empty | 1 | 1 | passed | 3727 |
| toolz-accumulate-empty | 1 | 1 | passed | 3466 |
| toolz-join-unmatched | 1 | 1 | passed | 7659 |
| toolz-getter-empty | 1 | 1 | passed | 3146 |
| boltons-backoff-constant | 1 | 1 | passed | 8453 |
| boltons-split-zero | 1 | 1 | passed | 3726 |
| boltons-chunked-bytes | 1 | 1 | passed | 12910 |
| boltons-remap-set | 0 | 1 | passed | 4202 |
| more-falsy-exception | 1 | 1 | passed | 9086 |
| more-batch-count | 1 | 1 | passed | 4233 |
| more-seekable-zero | 1 | 1 | passed | 15813 |
| more-combination-index | 1 | 1 | passed | 24017 |
| more-split-empty | 1 | 1 | passed | 11364 |
| more-value-chain-error | 1 | 1 | passed | 2039 |
| more-interleave-empty | 1 | 1 | passed | 3330 |
| more-reverse-empty-range | 1 | 0 | output_truncated | 34491 |
| more-negative-range-slice | 1 | 1 | passed | 20728 |
| more-ichunked-zero | 1 | 1 | passed | 4431 |
| more-bucket-missing-key | 1 | 1 | passed | 8115 |
| more-range-membership | 0 | 0 | output_truncated | 34207 |
| more-chunked-negative | 1 | 1 | passed | 6624 |
| more-range-equality | 1 | 0 | output_truncated | 34394 |
| more-sliced-negative | 1 | 1 | passed | 4775 |
| more-windowed-zero | 1 | 1 | passed | 3843 |
| more-predicate-sentinel | 1 | 1 | passed | 22090 |
| more-combination-size | 1 | 1 | passed | 12262 |
| more-permutation-exception | 1 | 1 | passed | 3373 |
| more-product-repeat | 1 | 1 | passed | 11094 |
| more-gray-partial-repeat | 1 | 1 | passed | 19380 |
| more-reversed-values | 1 | 1 | passed | 6255 |
| more-broadcast-single-use | 1 | 1 | passed | 4983 |
| more-last-typeerror | 1 | 1 | passed | 5864 |
| boltons-xfrange-descending | 1 | 1 | passed | 15661 |
| boltons-backoff-zero | 1 | 1 | passed | 20008 |
| boltons-repeat-equality | 1 | 1 | passed | 2491 |
| toolz-partition-length | 1 | 1 | passed | 17715 |
| toolz-merge-mapping | 1 | 1 | passed | 2161 |

完整实验：D:\project_other\CoreCoder\.tmp\real-defects\current-full-repair-v1-20261009\experiment.json
历史对照：D:\project_other\CoreCoder\.tmp\real-defects\reasoning-budget-v1-full-rerun-20261009\experiment.json
补丁、上下文、请求、Trace、公开/冻结检查和独立验收日志位于每项任务输出目录。
