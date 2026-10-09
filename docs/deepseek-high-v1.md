# 高思考能力试验

**最新完整结果（2026-10-09）：**同预算100次重跑完成，无思考28/50→高思考43/50（56%→86%），新增15、无丢失，Token增加263.03%。固定50项目标已达到；单轮已知任务池结果，不代表通用修复率。见 [完整报告](reasoning-budget-v1-full-rerun-20261009.md)。下文保留此前阶段记录。


目标为固定50项至少38项通过。当前最佳完整成绩33/50；连续重试与模型选取源码均未带来开发集净提升。目标代码已提供仍失败的案例提示，应检验模型的行为推理能力，而非继续扩大检索。

本轮保持原始固定源码证据、最多两次补丁调用、公开检查反馈、失败回滚与Worker外独立评分，使用DeepSeek Flash high思考模式。每项总预算60,000 Token，单次输出上限32,768（包括思考），上下文预算65,536，Worker超时1,200秒；API请求超时480秒，无自动重试。没有新增按案例编写的提示。

这是提高推理和预算的整体能力试验，与旧15,000预算无思考运行不是等成本对照。思考输出只记录存在与长度，不保存内容；API completion usage已包含思考，不重复计费。截断、空回答、缺失使用量及模型身份异常不算成功。

接口依据：[官方思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)、[Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion/)。无tools请求，不需要回传思考内容；top_p=0.95，未设置思考模式不支持的temperature。

- [高思考Provider](experiments/deepseek_high_provider_v1.py)
- [独立修复执行器](experiments/deepseek_high_repair_v1.py)
- [计量与截断测试](../tests/test_deepseek_high_provider.py)

聚焦验证8 passed、Ruff通过。旧冻结代码和默认Agent/API不变。开发集30项从原始源码新跑，保留失败及原有成功退步，不拼接历史补丁。所有临时文件与结果在D盘。

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp'
$env:TMP = $env:TEMP
python -B -m docs.experiments.deepseek_high_repair_v1 --scope development --output .tmp/real-defects/deepseek-high-v1-development-new
```

运行目录：`.tmp/real-defects/deepseek-high-v1-development`。完成后核对协议哈希与独立验收；只有完整50项新运行至少38项通过才能确认目标达成，开发集通过不能替代。


运行中阶段观察：前8项已完成且全部独立验收通过（complete=false，不是完整结果）。none-salt一次调用17,037 Token；help-eagerness通过；flag-default-map首轮公开失败后第二次修正通过，共41,660 Token。前8项共9调用、137,406 Token。该结果只证明已有正面信号，不能据此宣称达到75%。余下22项仍在同一执行进程中继续，未启动替代或重复运行。


## 开发集最终结果

complete=true，30/30，独立验收26/30（86.7%），历史冻结流程20/30；新增6项、无成功丢失：click-flag-default-map、click-help-eagerness、click-resource-exception、click-usage-empty、more-predicate-sentinel、toolz-join-unmatched。none-salt恢复了近期无思考试验的退步，但历史基线已经成功，因此不列作相对历史的新成功。

33次调用、446,080 Token，Worker累计1,525.34秒；Controls30/30（包含失败回滚），使用量无缺失，输入哈希核对通过。3项输出截断：flag-envvar、shared-default、range-membership；prompt-suffix公开通过但独立验收失败。后者不计成功。

[核对报告](deepseek-high-v1-development.json)。开发集结果不能证明50项目标；已启动 [同预算完整对照](reasoning-budget-compare-v1.md)，两组均60,000预算，从原始源码新跑50项，合计100次。对照尚未完成，最佳已完成全量成绩仍33/50。
