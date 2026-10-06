# BM25 / Dense 三轮配对复测 v1

## 目的

上一轮 11 项单次补丁对照中，Dense 比 BM25 多通过 pagination-cursor 一项。本轮检查这项差异能否在同一冻结配置下重复出现，并检查其他任务是否回退。

本轮是合成开发集的可复现性检查，不增加独立缺陷数量。temperature=0、固定模型与相同 Prompt 的重复结果不能视为 33 个新的独立任务，也不用于宣称统计显著性或真实仓库泛化。

## 交付

- `docs/experiments/vector_repair_repeat_v1.py`：校验前轮协议、模型、原适配器、语料与评分器；冻结三轮交替顺序；执行 66 次全新补丁及独立验证；生成完整矩阵与配对结果。
- `tests/test_vector_repair_repeat.py`：校验配对顺序、重复统计、缺失/重复运行拒绝、未知用量处理、Prompt 漂移诊断。

所有补丁仍由前轮 Worker 生成，独立评分仍使用原 verifier。没有修改修复 Prompt、依赖展开、JSON 应用器或失败案例；原冻结引擎保持一致。

## 固定协议

| 项目 | 配置 |
| --- | --- |
| 任务 | 前轮全部 11 个合成开发任务，每任务 BM25/Dense 各执行 3 次 |
| 输入 | 前轮复制的评分前 observations.json，不读取 targets/scores 或历史补丁作为输入 |
| 装填 | 相同 40 行 chunk 的冻结排名，前 5 个唯一文件，完整原文累计最多 6,000 字符；无依赖展开 |
| 模型 | qwen3.5:27b；temperature=0、reasoning_effort=none |
| 预算 | 修复 15,000 Token、context 16,000、输出 2,048、进程 600 秒、单项测试 15 秒 |
| 顺序 | 任务与轮次交替 BM25/Dense 先后顺序；共 66 个新分支 |
| 评分 | 原始隐藏目标测试和回归测试在干净评分副本执行 |
| 成本 | 本轮新增修复成本独立记账；Embedding 调用为 0，历史结果不混入分母 |

每个分支开始前核对引擎与两份适配器摘要、全部任务语料/清单/隐藏测试摘要及模型 digest。只有矩阵完整且无重复/缺失分支才生成最终分析；用量缺失记录为 unknown，不按 0 计算。

冻结标识（2026-10-06）：

```text
engine:              c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd
repair model:        7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e
observations:        a3dcd8c4b4dba89573cf0c0ccbe0463ab06a74e0faf8ef3b41e7e01ef8561cbb
source protocol:     57bed89496baf56f327de3bcc97d1ad5a2764c55549531a4c317a397bc00c24d
patch adapter:       c1eeb02886bc71068d0f4275822b2047e14e482f546a2a0c271ba2a9efb407d3
repeat adapter:      f6e5093283513f16bb2ce451a9c0f8c64178df647e94e1b27494212a4aea93c8
```

## 2026-10-06 实测与决策

全部 66 次新修复完成，每次均独立评分。模型身份、引擎、适配器、任务与评分器摘要保持一致，11 项的每个策略在三轮间 Prompt 摘要均相同。全部模型用量完整，没有预算停止、超时或基础设施错误。

| 策略 | 第一轮 | 第二轮 | 第三轮 | 合计 | 修复 Token |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 | 4/11 | 5/11 | 5/11 | 14/33（42.42%） | 28,535 |
| Dense | 4/11 | 4/11 | 4/11 | 12/33（36.36%） | 30,282 |

33 个任务/轮次配对：双方通过 12 对、双方失败 19 对、BM25 单独通过 2 对、Dense 单独通过 0 对。三轮仍只有 11 个不同任务，不把配对次数当作独立任务数。

| 任务 | BM25 三轮通过 | Dense 三轮通过 |
| --- | ---: | ---: |
| falsey-overrides | 3/3 | 3/3 |
| inclusive-date | 2/3 | 0/3 |
| retry-policy | 3/3 | 3/3 |
| tenant-cache | 3/3 | 3/3 |
| timeout-units | 3/3 | 3/3 |
| artifact-routing | 0/3 | 0/3 |
| checkout-rounding | 0/3 | 0/3 |
| event-replay | 0/3 | 0/3 |
| job-deadline | 0/3 | 0/3 |
| pagination-cursor | 0/3 | 0/3 |
| lease-lifecycle | 0/3 | 0/3 |

BM25 无效补丁 9 次、应用后验证失败 10 次；Dense 无效补丁 6 次、应用后验证失败 15 次。Dense 多消耗 1,747 个修复 Token（6.12%），通过数更少。新修复总用量为 58,817 Token、66 个模型调用；前轮成绩与成本不混入本轮分母，Embedding 新调用为 0。

**上一轮的 pagination-cursor 成功未复现。**Dense 三轮均因空 old 被补丁应用器拒绝；第一轮响应试图对 cursor_codec.py 使用空 old，且猜测游标为 `created|id`，但该模块已有 Base64/JSON 实现，源码未进入前 5 文件证据。前轮成功与本轮第一轮的证据清单及 Prompt 摘要均相同，输出却不同；temperature=0 没有在此次本机观测中保证一致输出。本实验没有定位模型运行时导致差异的具体原因，不把它归因于单一缓存或 GPU 机制。

BM25 的 inclusive-date 第二、三轮通过：补丁将 service.py 的结束边界比较由 `<` 改为 `<=`；第一轮失败。仅状态和输入一致仍不足以保证输出稳定，因此不按单次成功挑选策略。

结论：离线文件召回改善尚未转化为稳定修复收益。保留 BM25 与默认引擎，Dense/Hybrid 留在实验适配器；停止继续用相同配置追加复测，不将上一轮 5/11 宣传为可靠提升。这里得到的是开发集失败边界与复现证据，没有真实仓库泛化或统计显著性结论。

下一步在独立版本复用已有静态 Python import 解析，验证预算内补充公开依赖源码能否减少猜造辅助模块；固定原排名、字符预算和补丁约束，先核对证据，再运行对照。源码缺失是日志支持的待验证假设，不能保证解决所有语义错误。真实仓库与留出集验证仍是正式结论前的必要工作。

验证：23 项相关测试通过；全量 709 passed、1 skipped；Ruff 通过。原冻结引擎与前轮 Worker 文件未修改。

## 复跑与产物

在 corecoder conda 环境、项目根目录执行，输出目录必须不存在：

```powershell
python -m pytest tests/test_vector_repair_repeat.py tests/test_vector_repair.py tests/test_vector_retrieval.py -q
python -m docs.experiments.vector_repair_repeat_v1 --source .tmp/retrieval/vector-repair-v1 --output .tmp/retrieval/vector-repair-repeat-v1-rerun --validate-only
python -m docs.experiments.vector_repair_repeat_v1 --source .tmp/retrieval/vector-repair-v1 --output .tmp/retrieval/vector-repair-repeat-v1-rerun
```

先按 [前轮说明](vector-repair-v1.md) 构建 source 目录；源协议及适配器必须匹配。当前产物目录 `.tmp/retrieval/vector-repair-repeat-v1`：protocol.json 在模型调用前冻结，experiment.json 增量保存，matrix.json 为完成后的配对分析。`repeat-N/task/strategy` 下保留原始模型响应、Trace、补丁、独立测试日志。中断保留不完整结果，不把缺失分支默认为失败或自动填充旧成绩。
