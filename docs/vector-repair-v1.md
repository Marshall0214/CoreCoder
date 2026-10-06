# 三种检索策略的单次补丁对照 v1

## 研究问题

在修复模型、Prompt、证据装填和预算相同时，上一轮 Dense/Hybrid 的文件召回改善是否能转化为独立验证通过？

这是 11 个合成开发任务的一次探索对照，分别运行 BM25、Dense、Hybrid，共 33 个补丁。不是留出集评测，不是 Agent 工具循环，也不与此前 Click staged read-first 成绩合并。

## 实现与隔离

- `docs/experiments/vector_repair_v1.py`：校验评分前的检索观察、构造完整文件证据、冻结配置及轮换执行顺序、在独立进程生成补丁、在干净副本验证。
- `docs/experiments/vector_repair_analysis_v1.py`：只分析完整的 33 格矩阵；随后才用参考改动文件计算已装填证据的代理召回率。
- `tests/test_vector_repair.py`：验证完整原文与字符预算、语料版本、引用、排名一致性、评分字段拒绝及未完成批次不加载标签。

只读取上一轮 `.tmp/retrieval/vector-v1-final/observations.json`，不使用含 targets/scores 的 report.json。索引哈希、查询、chunk 路径/行号/源文件哈希与当前公开语料核对；Dense/Hybrid 必须覆盖所有原始 chunk。模型 Worker 不接收任务根目录、参考补丁或隐藏测试，只接收问题、允许修改文件、证据和配置。

独立验证器复用 `evals.runner.verify`：把允许范围内的候选源文件复制到新的评分副本，从原 fixture 获取回归测试和隐藏目标测试。只有补丁执行完成、目标及回归均通过，才记为 passed。模型运行包含进程超时与失败产物保存；这不是操作系统安全沙箱。

## 冻结协议

| 项目 | 配置 |
| --- | --- |
| 检索输入 | 上轮 11 项评分前冻结排名；本轮新增 Embedding 调用为 0 |
| 文件选择 | 每组唯一文件排名前 5，包括 Markdown |
| 装填 | 按排名读完整文件，累计最多 6,000 字符；超限跳过，不截断，不用额外文件补位 |
| 依赖展开 | 禁用；本轮只隔离排名差异 |
| 补丁 | 原 fixed-evidence baseline Prompt、JSON 精确 old/new 替换；一次请求，无反馈或重试分支 |
| 模型 | qwen3.5:27b，temperature=0，reasoning_effort=none |
| 预算 | 每组修复 Token 15,000、context 16,000、输出最多 2,048、进程 600 秒、单项验证 15 秒 |
| 顺序 | 任务间循环轮换 BM25/Dense/Hybrid 的先后顺序；一轮，不宣称统计显著性 |

“读完整文件”的装填复用了既有 pipeline 原则；它不是 Click 的 staged read-first 工作流，没有定位模型或候选池。检索器没有在本轮作为模型可调用工具运行。

修复模型摘要：`7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`。

冻结引擎摘要：`c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd`。实验适配器摘要、任务语料/清单/评分器摘要及执行顺序在批次开始前保存于 protocol.json。

## 2026-10-06 实测结果

全部 33 个分支完成独立验证；每组 11 次修复模型调用，返回 Token 用量均完整。没有预算预检查停止、超时或基础设施错误。

| 策略 | 通过 | 成功率 | 修复 Token | 无效补丁 | 已应用但验证失败 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 | 4/11 | 36.36% | 9,726 | 3 | 4 |
| Dense | 5/11 | 45.45% | 10,164 | 1 | 5 |
| Hybrid | 5/11 | 45.45% | 10,308 | 2 | 4 |

| 任务 | BM25 | Dense | Hybrid |
| --- | --- | --- | --- |
| falsey-overrides | 通过 | 通过 | 通过 |
| inclusive-date | 验证失败 | 验证失败 | 验证失败 |
| retry-policy | 通过 | 通过 | 通过 |
| tenant-cache | 通过 | 通过 | 通过 |
| timeout-units | 通过 | 通过 | 通过 |
| artifact-routing | 验证失败 | 验证失败 | 无效补丁 |
| checkout-rounding | 无效补丁 | 无效补丁 | 无效补丁 |
| event-replay | 验证失败 | 验证失败 | 验证失败 |
| job-deadline | 无效补丁 | 验证失败 | 验证失败 |
| pagination-cursor | 无效补丁 | 通过 | 通过 |
| lease-lifecycle | 验证失败 | 验证失败 | 验证失败 |

基础五项三组均 4/5；另外六项 BM25 为 0/6、Dense/Hybrid 为 1/6。总成绩变化集中在一个案例，没有得到跨多个困难任务的稳定改善。

Dense 比 BM25 多 438 个修复 Token（4.50%），Hybrid 多 582 个（5.98%）。新修复用量合计 30,198；上轮共享检索为 4,104 Embedding Token、22 次请求，本轮新增 Embedding 为 0。累计两阶段观测用量为 34,302 Token；两种模型的 Token 单列，不换算同一美元成本，不把共享检索重复算进三组。

三组实际执行与验证耗时合计分别约 96.63、65.23、68.30 秒，包含启动、模型加载/缓存与本机运行变化；这是一次轮换批次，不是证明 Dense 更快的性能基准，也不含历史检索时间。

## 有效差异与失败定位

`pagination-cursor`：BM25 只提供 docs/paging.md 和 api.py；模型试图修改未提供的源文件，被补丁作用域检查拒绝。Dense/Hybrid 都提供了 paging.py、offset_paging.py、query.py 等代码，并通过目标及回归测试。这给出一个“检索补足修复代码 → 合法补丁 → 独立验证通过”的开发案例。

但更多失败未被检索解决：

- `job-deadline`：Dense/Hybrid 提供 execution.py、budget.py 等更多代码，补丁可应用，但仍未通过完整行为验证。
- `checkout-rounding`：三组生成的 edits 含空 old，违反精确唯一匹配约束。保留拒绝结果，不在本批次放宽补丁权限。
- `event-replay`：已应用补丁仍未正确处理跨租户相同事件 ID 等行为；属于修复逻辑不足。
- `inclusive-date`：BM25 有日期参数类型不匹配错误；Dense 仍有日期边界结果错误。相同失败状态并不代表相同原因。
- `artifact-routing` 的 Hybrid 尝试修改未提供文件；`lease-lifecycle` 三组均未完整修复。

这次观察表明：提升文件 Recall@5 并不自动改善所有任务；证据完整性、修复推理和合法补丁输出均会影响最终结果。没有通过调整预算、反馈轮数或事后重试掩盖失败。

## 决策与下一步

保留默认引擎与检索配置。Dense 作为后续候选：本轮与 Hybrid 成功数相同、修复 Token 较少，Hybrid 尚未展示额外修复收益。下一步先对完整 11 项做预先冻结的三轮 BM25/Dense 配对复测，复用相同排名与装填，不修改本轮失败案例的 Prompt；单列重试成本，验证 pagination 收益是否重复。之后把协议迁移到真实仓库与留出任务。只在独立版本中研究依赖展开或结构化输出，不与检索对照混合归因。

验证：全量测试 702 passed、1 skipped；随后新增“未完成批次不读取评分标签”测试，当前修复模块 6 项全部通过；Ruff 与 diff whitespace 检查通过。模型结果与测试结果分别记录，代码测试通过不等于缺陷任务通过。

后续修正：[三轮配对复测](vector-repair-repeat-v1.md) 已完成 66 次新修复，BM25 14/33、Dense 12/33，pagination-cursor 的 Dense 通过未复现。以上单轮 5/11 只保留为探索结果，不能用作稳定提升声明；维持默认策略。

## 复跑

在项目根目录的 corecoder 环境中执行，输出目录必须不存在：

```powershell
python -m pytest tests/test_vector_repair.py tests/test_vector_retrieval.py -q
python -m docs.experiments.vector_repair_v1 --observations .tmp/retrieval/vector-v1-final/observations.json --output .tmp/retrieval/vector-repair-v1-rerun --validate-only
python -m docs.experiments.vector_repair_v1 --observations .tmp/retrieval/vector-v1-final/observations.json --output .tmp/retrieval/vector-repair-v1-rerun
python -m docs.experiments.vector_repair_analysis_v1 .tmp/retrieval/vector-repair-v1-rerun
```

先按 [离线检索说明](vector-retrieval-v1.md) 重建 observations，再执行修复；保留不同批次身份。本轮结果目录 `.tmp/retrieval/vector-repair-v1`：protocol.json 保存协议，experiment.json 增量保存全批次，matrix.json 保存完成后的分析，每项 task/strategy 目录含模型响应、Trace、补丁和两套独立测试日志。中断批次保留 complete=false，不自动补跑或合并。
