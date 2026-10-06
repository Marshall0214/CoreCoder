# 均衡区间策略：五任务迁移批次与适用性矩阵

## 本轮完成

固定 `public-balanced-v1` 算法及 12 行 / 前后 4 行窗口参数，完成其余五个已登记开发任务的同池装填对照。新增批量入口、完整性与成本汇总校验、离线矩阵分析；运行十次真实模型补丁调用，全部由父进程独立验证。没有新增定位、修改隐藏测试、追加任务专属 API 名字或根据中间结果调参。

每个任务两组使用相同历史定位 checkpoint、描述、源码范围、模型和预算。模型仍为 Ollama `qwen3.5:27b`，temperature=0、reasoning=none；证据上限 6,000 字符，补丁额度 15,000，验证保留 3,000，每组一次。策略执行顺序按任务交错。新协议冻结十个运行分支、候选来源、模型 digest 和适配器 SHA；非证据提示与候选池在所有配对中一致。

## 五任务主结果

| 任务 | read-first | balanced | read-first Token | balanced Token |
| --- | --- | --- | ---: | ---: |
| click-help-eagerness | 失败 | 失败 | 2,511 | 3,042 |
| click-flag-default-map | **通过** | 失败 | 2,627 | 2,774 |
| click-resource-exception | 失败 | 失败 | 3,205 | 2,731 |
| click-invoke-missing | **通过** | **通过** | 2,034 | 2,640 |
| click-shared-default | 失败 | 失败 | 2,572 | 2,947 |
| **本批次** | **2/5** | **1/5** | **12,949** | **14,134** |

本批次没有新增成功任务，出现一项回退 `click-flag-default-map`。balanced 比 read-first 多消耗 1,185 Token；不能作为更高效率或成功率的默认替代。

十个 Worker 均生成并应用补丁，没有 invalid_patch、预算拦截、超时或基础设施错误。失败统一由独立验证器记录为 failed_verification，保留在分母：原策略三次、新策略四次。原策略 resource-exception 同时未通过公开 Controls，其余运行公开 Controls 通过；公开回归通过仍不能证明目标缺陷被修复。Controls 均为约定小型公开回归，不代表完整上游测试。

这些状态只描述验收结果，未将所有失败自动归因于上下文。策略同时改变证据覆盖、顺序、区间边界和元数据；是否遗漏相关实现、引入干扰或模型推理失败，需要单独的机制证据。不能由 Token 或片段数量直接作因果判断。

## 与此前两个试验的探索性矩阵

| 任务 | read-first | balanced | 性质 |
| --- | --- | --- | --- |
| click-prompt-suffix | 失败 | **通过** | 前期单例正面结果 |
| click-flag-envvar | 失败 | 失败 | 前期跨文件迁移失败 |
| 本轮其余五个任务 | **2/5** | **1/5** | 本轮固定批次 |
| **七案例描述性汇总** | **2/7** | **2/7** | 一项收益与一项回退抵消 |

**七案例不是统一定位协议下的新基准。** prompt-suffix 使用较新的 definition 定位池，其余六个任务使用历史定位池；模型及补丁策略一致、每项内部是同池配对，但这只是按已登记开发案例拼接的探索性矩阵。每组一次，不满足正式多次重复或留出集评估条件。不得写成统计显著提升，也不能从 2/7 推断未来任务成功率。

七案例原策略补丁 Token 为 **19,312**，新策略为 **21,021**，均有返回 usage。主判断仍以本轮五任务批次为准，先前单例不能单独支持默认推广。

## 成本与工程验证

本轮新消耗 **27,083 Token、10 次模型调用**。五份历史共享定位去重为 **43,542 Token**；本批次包含历史定位与本轮调用的等价总成本 **70,625 Token**，历史费用没有再次发生。

七案例汇总的十四次已发生补丁调用为 **40,333 Token**；七份共享定位累计 **59,164 Token**，合计 **99,497 Token**。这是这组试验选取的历史输入与补丁调用口径，不是项目所有历史实验总消耗。

批量运行器拒绝缺失/重复分支，只有十次运行完成才能写 complete。汇总不丢弃失败，不重复计算同一任务的共享定位；分析器校验运行数、任务集合、同池身份和重复任务，保留未知用量标志，并分别输出五任务主结果与七案例探索汇总。

新增七项测试及相关装填、同池约束、独立评分和阶段回归共 **34 passed**，Ruff 通过。结束后再次校验冻结输入与代码；未跑全量测试，未执行 Git commit。旧协议和 CoreCoder 默认行为保持不变。

## 决策与后续

**本轮装填策略评估收敛：保持 read-first 默认，均衡策略作为可复现实验归档，不继续调整窗口参数追求这七个任务的分数。** 正面案例和负面结果都保留，可以展示源码版本校验、控制变量、独立评分、成本核算及适用性判断的工程能力。

后续回到计划中的检索主线：实现与验证代码向量检索后端，在固定分块、查询与 Top-K 下比较 BM25 / Dense / Hybrid 的离线召回；参考修复标注只用于评分，不进入 Agent 的检索输入。先证明召回机制及来源正确性，再选择是否进入修复对照，不预设向量检索一定解决当前失败。正式结论仍需更多仓库、留出任务与预先冻结的重复运行。

## 产物与复现

`.tmp/real-defects/balanced-transfer-batch-v1/` 包含 experiment.json、matrix.json、十次 Worker 输入/输出、模型响应、Trace、diff 和父进程 grading 日志。矩阵记录三个输入报告及分析脚本 SHA。运行产物被 Git 忽略；复现需要另外保留三组 admission 与历史 checkpoint。

```powershell
python docs/experiments/balanced_transfer_batch_v1.py --output .tmp/real-defects/balanced-transfer-batch-v1-rerun --validate-only
python docs/experiments/balanced_transfer_batch_v1.py --output .tmp/real-defects/balanced-transfer-batch-v1-rerun
python -m docs.experiments.balanced_transfer_analysis_v1 --batch .tmp/real-defects/balanced-transfer-batch-v1-rerun --prior .tmp/real-defects/balanced-interval-live-v1 --prior .tmp/real-defects/balanced-crossfile-live-v1 --output .tmp/real-defects/balanced-transfer-batch-v1-rerun/matrix.json
python -m pytest tests/test_balanced_transfer_batch.py tests/test_balanced_crossfile.py tests/test_balanced_intervals.py tests/test_real_tasks.py tests/test_staged_replay.py -q
```

输出目录和矩阵文件须为新路径。此前两个 pilot 的原报告只读，不再调用它们的模型。
