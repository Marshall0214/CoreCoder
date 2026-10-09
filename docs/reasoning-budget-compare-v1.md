# 同预算的思考模式完整对照

**最新完整结果（2026-10-09）：**同预算100次重跑完成，无思考28/50→高思考43/50（56%→86%），新增15、无丢失，Token增加263.03%。固定50项目标已达到；单轮已知任务池结果，不代表通用修复率。见 [完整报告](reasoning-budget-v1-full-rerun-20261009.md)。下文保留此前阶段记录。


目标：固定50项至少38项独立验收通过。开发集高思考试验出现净提升后，用两种配置从原始源码重新执行完整任务池，每项两组，共100次；不复用或拼接开发集补丁。

## 固定条件

| 条件 | 无思考 | 高思考 |
| --- | --- | --- |
| 模型别名 | deepseek-flash | 相同 |
| 总Token上限 | 60,000 | 相同 |
| 单次输出上限 | 32,768 | 相同，包含思考 |
| 上下文预算 | 65,536 | 相同 |
| 最大补丁调用 | 2 | 相同 |
| 请求 / Worker 超时 | 480 / 1,200秒 | 相同 |
| JSON、证据、检查、回滚、独立评分 | 相同 | 相同 |
| 思考配置 | disabled / none | enabled / high |

实际Token与耗时单独记录；相同预算上限不代表相同实际计算量。top_p均发送0.95，官方文档说明无思考时该参数被忽略而固定1.0，高思考时有效。因此对照的是两种思考配置整体，不能把差异归因为唯一算法因素。模型云端权重无法冻结，保存返回身份与fingerprint。

任务内交替两组顺序，每组独立请求，首轮回答不共享。已知任务池、单轮探索性结果，不能宣称盲测或跨仓库泛化。所有失败保留，公开检查通过而独立评分失败仍计失败；Controls通过包含失败回滚，不代表缺陷已经修好。

实现：[执行器](experiments/reasoning_budget_compare_v1.py)，[配置验证](../tests/test_reasoning_budget_compare.py)。默认Agent/API与旧冻结实验保持不变。

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp'
$env:TMP = $env:TEMP
python -B -m docs.experiments.reasoning_budget_compare_v1 --scope full --output .tmp/real-defects/reasoning-budget-v1-full-new
```

输出目录必须新建，全部写到D盘。结果完成后检查complete、100次执行、两组各50项、协议输入哈希、独立验收与使用量；只有满足这些条件后才报告完整修复率。

完整结果核查入口：[核查脚本](experiments/reasoning_budget_report_v1.py)、[核查测试](../tests/test_reasoning_budget_report.py)。核查两组首轮提示哈希相同、已验收补丁已发布且未超预算、进程无超时、实际Token与返回使用量一致；拒绝用运行中结果或重复任务生成完整报告。新增配置、Provider与核查聚焦验证14 passed。

```powershell
python -B -m docs.experiments.reasoning_budget_report_v1 --trial .tmp/real-defects/reasoning-budget-v1-full/experiment.json --output docs/reasoning-budget-v1-full.json
```


执行状态：开发集高思考26/30、相对历史20/30新增6且无丢失，故启动完整对照。当前运行目录`.tmp/real-defects/reasoning-budget-v1-full`，预计100次记录；complete=true以前不报告完整修复率。配置与Provider聚焦测试6 passed，Ruff与git diff --check通过。


执行期间完整回归：1468 passed、4 skipped（161.30秒）。当前100次模型对照仍在运行，尚未确认全量目标。
