# P0-2：localization-v1 人工开发任务

状态：用户已完成离线验收，新增 16 项测试通过（11.30 秒）、全部 219 项通过（41.96 秒）；unchanged 为 0/5，reference/scripted 均为 5/5。完整真实基线已运行，主验收 0/15（9 次目标验收失败、6 次预算终止）；详情见 [开发集基线与失败分析](localization-v1-baseline.md)。没有新增依赖，也没有实现 search_code 或修改 Agent 工具、预算与评分逻辑。

## 首次真实单项观察

2026-10-01，用户使用文中默认配置运行 pagination-cursor，汇总为 `.tmp/evals/localization-v1-pilot/summary-e316458e8c.md`，run_id 为 `pagination-cursor-1-83fd1e93d6`。

- 状态 budget_exceeded，验收未通过；无源码变化。目标测试失败，回归测试通过。
- 10 次 LLM 调用，Prompt 25,031、Completion 650，总用量 25,681 Token；端到端 39.22 秒。
- 30,000 Token 是任务累计预算。终止原因是下一次请求的估算输入加预留 2,048 输出无法放入剩余预算，实际用量未达到 30,000；不是连接错误，也不是上下文窗口溢出。
- 10 次工具调用：1 次 todo_write、8 次 read_file、1 次 glob。依次读取全部 7 个源码模块及可见测试；没有读契约文档，没有编辑源码，也没有运行可见测试命令。
- 依据已观察动作，将本次描述为“探索阶段耗尽预算，未进入修改”；模型内部推理未记录，不能判断它是否已在内部定位缺陷。

保留该 pilot，不覆盖或提高预算以获得成功。执行完整基线时仍使用相同的 30,000 Token / 12 轮条件，pilot 与正式 15 次结果单列。本次提示探索成本值得分析，但单个案例不能证明检索一定有效。

## 数据划分

原始 5 项任务保留在 evals/fixtures/，默认命令仍运行原始回归集；baseline-v1 的 15 次结果保持不变。

新任务单独位于 evals/fixtures/localization-v1/，运行时必须显式指定 `--suite evals/fixtures/localization-v1`。新旧任务不混算成功率。这是人工开发集，不是最终留出集，也不是公开历史缺陷。

相较旧任务，每项有 7 个源码模块、1 份契约文档和可见回归测试；问题描述提供入口及行为症状，但不列出缺陷文件或替换代码。包含有独立正确契约的相近功能模块；参考修复涉及两个文件，验收包含分别触发两个问题及组合场景的测试。

这些任务仍是小型程序，模型可以读取全部源码。不能预先认定它们足够困难，不能通过堆积无意义文件或放宽预算强行制造收益。首次基线可能仍全部通过；届时继续完善任务分布或分析 Token/证据效率，不声称成功率提升。

## 五项任务

| ID | 用户症状 | 需要理解的契约 | 相近功能 |
| --- | --- | --- | --- |
| checkout-rounding | 小数单价或优惠造成账单不一致 | 行金额先舍入再求和，折扣独立舍入，数量先相乘 | 旧报表使用另一舍入规则、展示与运费 |
| event-replay | 历史导入后计数缺失，追加批次处理不完整 | 事件标识的租户作用域，重复记录及后续记录处理 | 单租户导出键、通知键、快照 |
| pagination-cursor | 连续翻页遗漏记录，时间戳相同更明显 | 复合排序键、续页边界、前瞻记录及终止条件 | offset 分页、倒序 feed、标题搜索 |
| artifact-routing | 构建机归档目的地错误，规则优先级未生效 | 路径和模式规范化，优先级与同级顺序 | 原始匹配预览、顺序通知 |
| job-deadline | 持续失败时超过任务总期限 | 请求及等待共享剩余时间，重试计数与终止条件 | 不限总期限的退避预览、健康检查 |

每项的 workspace 是 Agent 可读输入，包括正常业务契约和可见测试。父目录的 reference.json、evaluation.json 和 hidden_tests 不复制到候选工作区，不参与将来的检索索引。

evaluation.json 是评测侧文件级诊断标注，包含入口链路相关文件及参考修改文件。相关文件包含契约文档；将来用于文件检索指标时要明确源码与文档口径。参考修改不是唯一合法解法，评分器继续根据行为、回归和范围验收。

## 用户验收步骤

在项目根目录、corecoder 环境执行。

### 1. 新增测试与完整回归

```powershell
python -m pytest tests/test_localization_tasks.py -q
python -m pytest tests -q
```

当前预期分别为 **16 passed**、**219 passed**；这是预期值，不是已执行结果。

新增测试验证：新旧任务分开；缺陷版本目标失败但回归通过；参考与离线工具修复通过；单独应用任一参考修改仍不能通过完整验收；评测侧标注路径有效且不进入工作区。

若失败，先反馈 pytest 输出或失败任务的 report.json / 测试日志。此阶段不运行模型。故意带缺陷的 fixture 代码可能有未使用的导入，不使用自动修复工具重写它们。

### 2. 验收新开发集评分

```powershell
python -m evals --suite evals/fixtures/localization-v1 --mode unchanged --output .tmp/evals/localization-v1-acceptance
python -m evals --suite evals/fixtures/localization-v1 --mode reference --output .tmp/evals/localization-v1-acceptance
python -m evals --suite evals/fixtures/localization-v1 --mode scripted --output .tmp/evals/localization-v1-acceptance
```

预期 unchanged 五项 failed_verification，reference/scripted 五项 passed。unchanged 返回码 1，其余返回码 0。后两种使用参考答案，不是模型效果。

原始回归集仍可使用不带 --suite 的命令；本次没有改变原始任务。新开发集 scripted 每项包含两组 read/edit，再执行可见测试与完成回答，在现有 12 轮限制内运行。

### 3. 提交任务代码，试跑一个真实任务

验收通过后检查并提交本次代码与文档，记录 commit，然后执行：

```powershell
python -m evals --suite evals/fixtures/localization-v1 --mode live --task pagination-cursor --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --output .tmp/evals/localization-v1-pilot
```

依然使用原有工具与默认预算，不提供参考答案。失败也是结果，先从 Trace 判别定位、理解契约、只修复一个问题、补丁错误或预算不足。

### 4. 生成无新增检索的开发集基线

单项确认执行和报告完整后，再执行：

```powershell
python -m evals --suite evals/fixtures/localization-v1 --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --repeat 3 --output .tmp/evals/localization-v1-baseline
```

共 15 次。当前有原生 glob/grep 工具，因此是“未新增 search_code”的基线，不是完全无搜索的基线。保留全部结果并备份原始产物；不与 baseline-v1 的简单任务混合报告，不选择性重跑。

提供本次 summary 路径后，再整理失败分布、Token 和工具耗时，决定是否继续增加任务定位难度。

## 检索实验的后续边界

本次只交付任务。随后增加统一 search_code，先实现关键词召回及统一结果格式。新工具会改变 Schema 和 Prompt，因此必须在共同接口下重新生成对照基线；不能把当前旧工具结果当作“仅检索后端改变”的因果证据。

先使用同 Schema 的无证据控制与关键词配置，固定证据预算及结果格式，再追加向量和混合检索；原生 read/glob/grep 的可用性保持一致。精确实验设置在实现前冻结。

任务难度与作用域通过实测确认；最终的真实仓库效果仍需外部历史缺陷、容器环境和独立留出集。
