# 50 个真实缺陷：完整基线测试与错误分类

## 结论

全部 50 个任务重新运行，独立目标与正常行为检查均通过 21/50；这是扩充后的基线，不是策略提升结果。

模型调用 50 次，返回 Token 145978，worker 耗时合计 633.8354 秒（不含入库和评分）。

## 任务池和协议

- 保留原 30 个任务，新增 20 个不同上游提交的缺陷；五个仓库，开发集 30、heldout 20。
- 全部任务先复现：before 的 Target 失败、Controls 通过；after 的两组检查均通过。模型看不到 reference 或两组私有检查。
- 固定 qwen3.5:27b、模型 digest、6000 字符完整函数 BM25 上下文、最多 5 个函数、依赖深度 0；单次修复，无工具和反馈重试。
- 继续采用唯一原文匹配替换及独立评分。无效补丁、越界修改或正常行为回归均不能计为成功。
- 每任务最多 15000 Token、输出 2048 Token、600 秒。全部任务同一设置，旧 30 个任务也重新调用模型。
- 全部结果保留，不因模型表现排除或重跑任务；旧版 12/30 不与本次 50 个任务直接比较为提升。

## 按任务缺陷类型

| 缺陷类型 | 任务数 | 通过 |
|---|---:|---:|
| 回调与异常传播 | 7 | 3 |
| 默认值与边界条件 | 14 | 6 |
| 数值与序列一致性 | 9 | 3 |
| 参数校验 | 8 | 7 |
| 状态与迭代器消耗 | 7 | 0 |
| 类型与表示兼容性 | 5 | 2 |

## 按修复结果

| 结果类别 | 数量 |
|---|---:|
| target_failed | 22 |
| passed | 21 |
| control_regression | 3 |
| invalid_patch | 3 |
| output_truncated | 1 |

control_regression 优先记录正常行为失败；若目标也失败，另加 target_also_failed 标签。invalid_patch 优先于评分通过，防止误计。

分类记录的是可观察结果。目标检查失败不能直接证明模型推理错误或检索缺失，根因保留 not_established；后续需用检索对照与失败轨迹验证。

## 逐任务结果

| 任务 | split | 缺陷类型 | 结果 |
|---|---|---|---|
| click-usage-empty | development | 默认值与边界条件 | target_failed |
| click-echo-empty-bytes | development | 类型与表示兼容性 | passed |
| click-style-color-validation | development | 参数校验 | passed |
| itsdangerous-none-salt | development | 默认值与边界条件 | target_failed |
| itsdangerous-future-age | development | 数值与序列一致性 | passed |
| itsdangerous-malformed-time | development | 回调与异常传播 | passed |
| click-help-eagerness | development | 状态与迭代器消耗 | target_failed |
| click-flag-default-map | development | 默认值与边界条件 | target_failed |
| click-resource-exception | development | 回调与异常传播 | target_failed |
| click-flag-envvar | development | 默认值与边界条件 | target_failed |
| click-prompt-suffix | development | 类型与表示兼容性 | target_failed |
| click-invoke-missing | development | 默认值与边界条件 | passed |
| click-shared-default | development | 状态与迭代器消耗 | target_failed |
| toolz-interpose-empty | development | 默认值与边界条件 | control_regression |
| toolz-accumulate-empty | development | 默认值与边界条件 | passed |
| toolz-join-unmatched | development | 默认值与边界条件 | target_failed |
| toolz-getter-empty | development | 默认值与边界条件 | passed |
| boltons-backoff-constant | development | 数值与序列一致性 | target_failed |
| boltons-split-zero | development | 默认值与边界条件 | passed |
| boltons-chunked-bytes | development | 类型与表示兼容性 | target_failed |
| boltons-remap-set | heldout | 类型与表示兼容性 | target_failed |
| more-falsy-exception | heldout | 回调与异常传播 | invalid_patch |
| more-batch-count | heldout | 参数校验 | passed |
| more-seekable-zero | heldout | 状态与迭代器消耗 | target_failed |
| more-combination-index | heldout | 数值与序列一致性 | passed |
| more-split-empty | heldout | 默认值与边界条件 | invalid_patch |
| more-value-chain-error | heldout | 回调与异常传播 | passed |
| more-interleave-empty | heldout | 默认值与边界条件 | passed |
| more-reverse-empty-range | heldout | 数值与序列一致性 | invalid_patch |
| more-negative-range-slice | heldout | 数值与序列一致性 | target_failed |
| more-ichunked-zero | development | 参数校验 | passed |
| more-bucket-missing-key | development | 状态与迭代器消耗 | target_failed |
| more-range-membership | development | 数值与序列一致性 | target_failed |
| more-chunked-negative | development | 参数校验 | target_failed |
| more-range-equality | development | 数值与序列一致性 | target_failed |
| more-sliced-negative | development | 参数校验 | passed |
| more-windowed-zero | development | 参数校验 | passed |
| more-predicate-sentinel | development | 回调与异常传播 | target_failed |
| more-combination-size | development | 参数校验 | passed |
| more-permutation-exception | development | 回调与异常传播 | target_failed |
| more-product-repeat | heldout | 状态与迭代器消耗 | control_regression |
| more-gray-partial-repeat | heldout | 状态与迭代器消耗 | control_regression |
| more-reversed-values | heldout | 数值与序列一致性 | target_failed |
| more-broadcast-single-use | heldout | 状态与迭代器消耗 | target_failed |
| more-last-typeerror | heldout | 回调与异常传播 | passed |
| boltons-xfrange-descending | heldout | 数值与序列一致性 | passed |
| boltons-backoff-zero | heldout | 默认值与边界条件 | output_truncated |
| boltons-repeat-equality | heldout | 默认值与边界条件 | passed |
| toolz-partition-length | heldout | 参数校验 | passed |
| toolz-merge-mapping | heldout | 类型与表示兼容性 | passed |

## 实际覆盖与局限

新增来源为 MoreItertools 15、Boltons 3、Toolz 2。任务数量增加，仓库种类仍是五个；相关函数和缺陷家族有重叠，不能视为 50 个独立业务场景。

构造者查看公开修复以编写检查；heldout 仅用于策略调参隔离，包含已跑过基线的旧 10 个任务和新 10 个任务，不保证预训练未见。新任务多数单文件，不证明跨文件修复能力。

Target/Controls 是手写契约检查，并未执行全部上游测试。部分描述提供 API 名称，因此难度与真实用户模糊报错不同。检查方法数不等于任务数。

## 工程验证

Windows 全量：1,198 passed、2 skipped，192.03 秒；专项 17 passed；新增代码与检查文件 Ruff 通过。没有重跑 Linux、Docker 或 HTTP。

## 复现

在仓库根目录和 corecoder 环境执行：

```powershell
python -m docs.experiments.expanded_admission_v2 --base .tmp/real-defects/expanded-admission-v1-certified-v2/admission.json --output .tmp/real-defects/expanded-admission-v2-new
python -m docs.experiments.expanded_baseline_v2 --admission .tmp/real-defects/expanded-admission-v2-new/admission.json --output .tmp/real-defects/expanded-baseline-v2-new
```

需保留历史入库快照与 `.tmp/expanded-research-v1` 的提交元数据；源代码 ZIP 在 D 盘缓存。当前并非仅 clone 仓库即可离线复现的独立数据包。模型须与冻结 digest 一致。

结果：[任务清单](expanded-suite-v2.json)、[机器可读结果和分类](expanded-baseline-v2.json)。

下一步仅根据开发集失败分布选择一个核心优化，在固定任务和预算下比较；heldout 不用于逐题调整提示词。
