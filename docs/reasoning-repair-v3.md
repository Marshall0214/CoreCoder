# 本地 Qwen 扩大预算 thinking 可行性试验

## 目的与范围

保留历史 Qwen 完整 50 项反馈修正基线（32/50），检查此前 8,192 生成 Token 上限是否掩盖了本地 thinking 的修复能力。本轮不使用云端 API，不修改生产默认配置。

预先固定六项开发集任务：历史失败 click-usage-empty、more-predicate-sentinel、toolz-join-unmatched、click-flag-default-map，以及历史成功 click-echo-empty-bytes、itsdangerous-none-salt。该样本有意包含失败，不能用六项通过率估计完整任务池通过率。

## 协议

- 同一 Ollama qwen3.5:27b，校验冻结模型 digest；原生 `/api/chat` 的 `think=false/true` 对照。
- 两组共同使用 temperature=0.6、top_p=0.95、top_k=20、min_p=0、presence_penalty=0、repeat_penalty=1、seed=17。
- 每次生成上限 32,768 Token，累计请求与生成预算 60,000 Token，上下文 40,960 Token；思考计入生成消耗。
- 最多两次补丁生成；每次原生请求超时 1,200 秒，任务 Worker 超时 2,700 秒。
- 每个任务交替两组执行顺序，分别发起全新请求；相同初始提示、公开反馈、保持性验证及失败回滚。独立验收信息不反馈给模型。
- 留存请求、最终输出、用量与思考长度元数据，不保存思考正文；所有临时数据位于 D 盘项目 `.tmp`。

相较历史 64% 基线，本轮还改变了采样、接口及预算，因此不能把差异全部归因于 thinking；本轮两组之间才是相同配置下的 think 开关对照。已知任务池单次运行不构成泛化结论。

## 执行与结果

入口：`python -B -m docs.experiments.reasoning_repair_compare_v3 --scope pilot --output .tmp/real-defects/reasoning-repair-v3-pilot-20261009`

原始结果位于上述目录的 `experiment.json`；只有 `complete=true` 且包含 12 条记录时才能作为完整六项对照。应统计独立验收成功、截断、公开验证失败、原成功丢失、Token 和耗时，并核对两组初始提示 hash 一致性。

针对适配器、用量计入、截断拒绝、配对报告及原有适配器的测试：17 passed。

2026-10-09 已启动真实模型运行。首项 click-usage-empty 的无思考组独立验收通过，7,003 Token、42.594 秒；其思考组尚未返回，暂无完整对照结论。已核对首项实际请求的初始提示、采样和预算一致。运行期间显卡占用约 19.5 GiB，利用率 98%。这些是运行中观察，不是最终六项结果。

完成后运行 `python -B -m docs.experiments.reasoning_repair_report_v3 .tmp/real-defects/reasoning-repair-v3-pilot-20261009/experiment.json`，汇总器会拒绝不完整记录或首次提示不一致的对照。

## 最终结果（2026-10-09）

12/12 次运行已完成，执行器正常退出，六项配对首次提示 hash 全部一致，无缺失 Worker 用量记录。以上运行中状态已被本节最终结果取代。

| 指标 | 无思考 | Thinking |
| --- | ---: | ---: |
| 独立验收通过 | 3/6 | 2/6 |
| 模型调用 | 11 | 9 |
| 累计 Token（含思考） | 35,773 | 73,862 |
| Worker 累计耗时 | 135.93 秒 | 1,094.28 秒 |
| 截断调用 | 0 | 1 |

Thinking 没有新增成功，丢失 click-usage-empty 一项；Token 为无思考的约 2.06 倍，耗时约 8.05 倍。

| 任务 | 无思考 | Thinking |
| --- | --- | --- |
| click-usage-empty | 通过 | 32,768 生成 Token 后截断，约 719 秒 |
| more-predicate-sentinel | 公开验证失败 | 公开验证失败 |
| toolz-join-unmatched | 通过 | 通过 |
| click-flag-default-map | 公开验证失败 | 公开验证失败 |
| click-echo-empty-bytes | 通过 | 通过 |
| itsdangerous-none-salt | 公开验证失败 | 公开验证通过，但独立 Target 与 Controls 均未通过 |

结论：本轮不将 thinking 提升为默认配置，不继续扩大该配置到全量 50 项。扩大输出空间没有消除所有截断；其余失败也包含已输出完整补丁但语义错误、公开检查未覆盖的回归，不能靠继续增加思考 Token 认定可以解决。后续优先审计失败补丁的上下文缺失和错误假设，再决定是否增加定向代码读取或候选补丁验证。

原本的 32/50（64%）全量基线保持不变。本轮六项包含历史失败且更改了采样及预算，3/6、2/6 只能作为本轮配对结果，不能当作整体修复率下降，也不能用于替换历史基线。
