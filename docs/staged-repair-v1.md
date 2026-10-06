# 分阶段真实修复试验 v1

## 为什么做

预算诊断的 21 次运行均未修复通过：20 次没有修改，唯一修改发生在约 96k Token 后。下一步是限制探索，让模型在已有证据上尽早尝试补丁，而不是继续提高总预算。

## 做了什么

新增可选 `staged` 工作流，默认 `agent-loop` 和历史基线保持原协议。入口为 `evals/real_tasks.py`，实现为 `evals/staged_repair.py`；批量清单是 `evals/real_defects/staged-suite-v1.json`。

1. **只读定位**：先按公开缺陷描述获取符号及依赖片段；模型只可调用 read_file、grep、glob。read_file 最多返回 120 行 / 6,000 字符，定位最多 4 次模型调用，累计预算上限为总预算的 40%。每次请求告知剩余定位预算。
2. **结构化修改**：丢弃定位对话历史，只携带经源码哈希、行内容验证的阅读片段和初始符号证据。完整片段去重并限制到 6,000 字符；阅读片段优先，不能放入的片段跳过。只允许一次 JSON 补丁请求，预算最多为总预算的 50%，同时受剩余总预算约束。old 必须出现在提供的证据中、在完整文件内唯一，且文件哈希未变化；所有编辑校验后才写入。
3. **公开验证**：执行独立环境中的 Controls 正常行为测试，没有模型调用。父进程另行在新副本中运行隐藏 Target 和 Controls，只有两者通过且 Worker 正常完成才计为成功。隐藏结果不用于后续模型修复。

定位预检查停止会切换到补丁阶段；API 错误仍记录为错误。无证据直接停止；补丁无效或预算耗尽时源码不因此获得未校验的修改，仍运行公开检查。空 edits 仅表示执行结束，不表示修复成功。

30k 档分配为定位 12k、补丁最多 15k、预留 3k。这里的 10% 是未使用的模型预算余量：公开验证只消耗时间，当前没有验证后的模型恢复轮次，不能宣称已经实现反馈修复。输出采用剩余预算策略，保留现有预检查及返回用量检查；这不是服务端收费硬上限。

Trace 记录阶段、预算、实际源码变化；Worker 报告记录阶段 Token、证据清单及证据/提示/工具 Schema 哈希。修改阶段不使用通用 Agent 轮次，不能把阶段序号当作 Agent round。

## 试验边界

固定 qwen3.5:27b、temperature=0、reasoning_effort=none、总预算 30k、上下文 16k、输出上限 2,048、Worker 超时 600 秒、测试超时 15 秒。7 个 Click 开发任务全部保留在分母中，每个先运行一次。

此协议同时改变符号检索、只读工具集合、阅读限制、上下文收敛、预算分配和 JSON 补丁输出，是**组合工作流试验**，不能将收益单独归因于检索或阶段预算。模型没有收到上游补丁、隐藏用例或答案文件位置。7 个任务已用于开发，不是留出集，也不能代表仓库级泛化能力。

`staged-control-suite-v1.json` 冻结相同任务、模型和总预算的 agent-loop 对照配置，供后续配对多轮运行使用。历史预算诊断仅提供背景，不能替代同版本多轮对照。

## 复跑

```powershell
python -m pytest tests -q
python -m evals.real_suite --suite evals/real_defects/staged-suite-v1.json --mode live --admission original=.tmp/real-defects/mixed-original-admission-v1/admission.json --admission crossfile=.tmp/real-defects/crossfile-admission-v2/admission.json --admission expansion=.tmp/real-defects/expansion-admission-v1/admission.json --output .tmp/real-defects/staged-live-v1-rerun
```

输出目录必须为新目录；复跑对照时换为 `staged-control-suite-v1.json` 并使用另一新目录。`--repeat 3` 会记录重复覆盖值。上述准入文件必须已经存在，并共同使用此前隔离的 stdlib 环境，不要混用旧 Conda 准入。

## 本轮结果

全量测试：590 passed、1 skipped；本轮改动 Ruff 检查通过。真实分阶段运行已完整完成 7 次，每个任务一次；全部产生非空源码修改，全部 Worker 正常完成，未发生补丁阶段预算停止或越界修改。

| 任务 | 定位 Token | 补丁 Token | 总 Token | 独立验收 |
| --- | ---: | ---: | ---: | --- |
| click-help-eagerness | 10,653 | 2,837 | 13,490 | 失败 |
| click-flag-default-map | 6,830 | 2,627 | 9,457 | 通过 |
| click-resource-exception | 11,479 | 3,205 | 14,684 | 失败，正常行为也报错 |
| click-flag-envvar | 8,081 | 3,533 | 11,614 | 失败 |
| click-prompt-suffix | 11,688 | 3,039 | 14,727 | 失败 |
| click-invoke-missing | 7,867 | 2,034 | 9,901 | 通过 |
| click-shared-default | 6,710 | 2,485 | 9,195 | 失败 |

成功率为 2/7；总已知输入+输出 Token 为 83,068，未知用量调用为 0，任务累计耗时 148.39 秒（包括 Worker、独立验收等）。每个任务只在最后补丁阶段写入一次，因此首次修改 Token 与上述总 Token 相同。定位完成调用数为 2–4 次，六个任务因定位预算预检查停止而切换阶段，一个达到 4 次调用上限；阶段停止不等于整个任务停止。

公开 Controls 通过 6/7，只有其中 2 个通过独立缺陷验收。resource-exception 的补丁向 ExitStack.close 传入不支持的 exc_info 参数，正常退出也因此报错；其余失败补丁没有修复全部目标行为。保留失败补丁及独立评分，不根据隐藏用例即时调整协议。

原始报告：`.tmp/real-defects/staged-live-v1/suite-report.json`，各任务目录含 trace、原始 JSON 补丁、公开检查及独立评分日志。实现源码哈希为 `8a51f3addc335c708674d77d8e29df87e1e4da16ded591cdb702059f3a0738d1`；模型摘要为 `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`。报告目录被 Git 忽略，需要自行保留或归档；文档保存统计摘要。

同版本对照已完整完成，双方使用相同源码哈希、模型摘要、任务清单、总预算与独立测试环境；每个任务各运行一次，未出现超时、API 错误或轮数停止。对照的 7 次均为 cumulative_preflight，且没有实际源码变化。

| 指标 | 原 agent-loop | staged |
| --- | ---: | ---: |
| 独立验收通过 | 0/7 | 2/7 |
| 实际修改任务 | 0/7 | 7/7 |
| 全任务预算停止 | 7/7 | 0/7 |
| 总输入+输出 Token | 181,437 | 83,068 |
| 累计任务耗时（秒） | 138.03 | 148.39 |

对照报告：`.tmp/real-defects/staged-control-live-v1/suite-report.json`。两个目录均保存 `analysis.json`，由 Trace 汇总首次修改及停止原因。所有调用用量已知；此次 staged 更少消耗 Token，但累计耗时略高，不能宣称执行速度提升。回归检查仅覆盖已发布 Controls，不是完整上游测试套件。

当前证据支持“这套组合流程让模型在预算内更早开始修改，且部分任务首次修复通过”。不能证明稳定提升、单项因果或跨仓库收益。下一步保持实现不变，进行同配置双方各 3 次重复，再在固定工作流内消融证据选择；不立即按失败任务答案调整策略。
