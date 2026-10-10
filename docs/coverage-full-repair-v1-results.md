# 当前策略完整 50 项修复评测

独立验收：历史 43/50 → 本轮 47/50。新增 5，丢失 1。
本轮 54 次模型调用，648,593 Token；相对历史 -9.38%。
审计：通过。

全部任务从原始源码重新生成候选，没有复用历史回答。原模型别名、预算及独立评分保持；当前检索应用于全部任务，新增公开契约仅应用于 envvar。已知任务池、单轮历史对比，不能独立归因算法收益，也不是盲测。

| 仓库 | 数量 | 历史通过 | 本轮通过 |
| --- | ---: | ---: | ---: |
| boltons | 7 | 7 | 7 |
| click | 10 | 6 | 9 |
| itsdangerous | 3 | 3 | 3 |
| more_itertools | 24 | 21 | 22 |
| toolz | 6 | 6 | 6 |

新增成功：click-usage-empty, click-resource-exception, click-invoke-missing, more-reverse-empty-range, more-range-equality
历史成功丢失：more-negative-range-slice

失败分类（截断优先；细节保留最终状态和独立分组）：

- public_validation_failed: 1
- output_truncated: 2

| 任务 | 历史 | 本轮 | 结果分类 | Token |
| --- | --- | --- | --- | ---: |
| click-usage-empty | 0 | 1 | passed | 9534 |
| click-echo-empty-bytes | 1 | 1 | passed | 20681 |
| click-style-color-validation | 1 | 1 | passed | 12249 |
| itsdangerous-none-salt | 1 | 1 | passed | 16942 |
| itsdangerous-future-age | 1 | 1 | passed | 3389 |
| itsdangerous-malformed-time | 1 | 1 | passed | 12866 |
| click-help-eagerness | 1 | 1 | passed | 12654 |
| click-flag-default-map | 1 | 1 | passed | 3645 |
| click-resource-exception | 0 | 1 | passed | 13525 |
| click-flag-envvar | 1 | 1 | passed | 56222 |
| click-prompt-suffix | 1 | 1 | passed | 9516 |
| click-invoke-missing | 0 | 1 | passed | 20224 |
| click-shared-default | 0 | 0 | public_validation_failed | 58249 |
| toolz-interpose-empty | 1 | 1 | passed | 2538 |
| toolz-accumulate-empty | 1 | 1 | passed | 3126 |
| toolz-join-unmatched | 1 | 1 | passed | 6790 |
| toolz-getter-empty | 1 | 1 | passed | 2529 |
| boltons-backoff-constant | 1 | 1 | passed | 16686 |
| boltons-split-zero | 1 | 1 | passed | 2980 |
| boltons-chunked-bytes | 1 | 1 | passed | 14509 |
| boltons-remap-set | 1 | 1 | passed | 3760 |
| more-falsy-exception | 1 | 1 | passed | 6508 |
| more-batch-count | 1 | 1 | passed | 2583 |
| more-seekable-zero | 1 | 1 | passed | 17974 |
| more-combination-index | 1 | 1 | passed | 18770 |
| more-split-empty | 1 | 1 | passed | 13536 |
| more-value-chain-error | 1 | 1 | passed | 2078 |
| more-interleave-empty | 1 | 1 | passed | 3832 |
| more-reverse-empty-range | 0 | 1 | passed | 2209 |
| more-negative-range-slice | 1 | 0 | output_truncated | 34535 |
| more-ichunked-zero | 1 | 1 | passed | 5529 |
| more-bucket-missing-key | 1 | 1 | passed | 9164 |
| more-range-membership | 0 | 0 | output_truncated | 34221 |
| more-chunked-negative | 1 | 1 | passed | 3765 |
| more-range-equality | 0 | 1 | passed | 12971 |
| more-sliced-negative | 1 | 1 | passed | 7525 |
| more-windowed-zero | 1 | 1 | passed | 4019 |
| more-predicate-sentinel | 1 | 1 | passed | 18812 |
| more-combination-size | 1 | 1 | passed | 10906 |
| more-permutation-exception | 1 | 1 | passed | 2757 |
| more-product-repeat | 1 | 1 | passed | 11801 |
| more-gray-partial-repeat | 1 | 1 | passed | 34071 |
| more-reversed-values | 1 | 1 | passed | 8458 |
| more-broadcast-single-use | 1 | 1 | passed | 9834 |
| more-last-typeerror | 1 | 1 | passed | 5819 |
| boltons-xfrange-descending | 1 | 1 | passed | 15148 |
| boltons-backoff-zero | 1 | 1 | passed | 26405 |
| boltons-repeat-equality | 1 | 1 | passed | 2676 |
| toolz-partition-length | 1 | 1 | passed | 17477 |
| toolz-merge-mapping | 1 | 1 | passed | 2596 |

完整实验：D:\project_other\CoreCoder\.tmp\real-defects\coverage-full-repair-v1-20261010\experiment.json
历史对照：D:\project_other\CoreCoder\.tmp\real-defects\current-full-repair-v1-20261009\experiment.json
补丁、上下文、请求、Trace、公开/冻结检查和独立验收日志位于每项任务输出目录。

## 本轮结论与剩余问题

完整新跑 50 项，独立通过 47 项（94%），相对最近完整 43/50 净增四项（+8 个百分点）。五项退步全部恢复，但 more-negative-range-slice 新出现首轮截断，不能表述为无成功丢失。

- click-shared-default：两轮均生成并应用了有效格式补丁，但公开复现检查仍失败，最终回滚。不能靠结构约束证明语义正确。
- more-negative-range-slice：首轮 finish_reason=length，32,768 生成 Token 全用于思考，没有完整补丁；这是本轮新增退步。
- more-range-membership：同样首轮思考耗尽 32,768 额度，未得到完整补丁。

五项恢复与目标覆盖改进一致，但本轮同时改变检索与补丁约束，且使用独立随机生成，不能分离各自贡献或排除随机波动。最终 Controls 50/50 包含三项失败回滚后的检查，验收范围为手工 Target/Controls，不代表全量上游测试。

本轮累计工作进程耗时约 38.1 分钟；54 次调用，648,593 Token，相对最近完整对照减少 9.38%。未新增预算、调用次数或截断后重试。

下一步先离线检查三项上下文和候选补丁，分别处理语义缺口与思考截断；如改动生成额度或截断恢复策略，应单独版本化并注明协议变化。
