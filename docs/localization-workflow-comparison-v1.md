# localization-v1 完整工作流对照

## 预先固定的协议

目的：检验两项试点的有效审查与修复表现能否在完整五项合成任务中复现。比较整体工作流，不能将差异解释为单项检索收益或单独的 Schema 收益。

| 组别 | 协议 | 修复提示 | 调用机会 |
| --- | --- | --- | --- |
| single-patch | bounded-pipeline-v1 | contract-coverage | 单次补丁调用 |
| schema-feedback | public-contract-feedback-v4-schema | contract-coverage | 测试生成、Schema 审查、初次补丁，必要时一次反馈 |

两组共用 Qwen `qwen3.5:27b`、temperature 0、reasoning none、单次输出 2048 Token、累计 30000 Token、上下文估计 16000、worker 180 秒、测试 15 秒；keyword K=5、静态依赖深度 2、完整证据预算 6000 字符、path 排序。

artifact-routing、checkout-rounding、event-replay、job-deadline、pagination-cursor 各三轮，每轮逐任务成对运行，并按轮次/任务交替先后组别，共 30 次。每次从干净任务工作区开始。未清空 Ollama 缓存，交错顺序缓解运行时偏差，不声称缓存被完全控制。

记录源码、依赖及任务完整文件哈希；开始前及每次运行后检查，变化即停止并保留部分结果。本地模型 digest 按实际运行元数据固定，出现不同 digest 则停止；未获得 digest 时不能声称版本已验证。各次失败均计入分母，不挑选重跑、不修改失败输出。

单调用基线不使用弱化提示，两组初次补丁提示和证据构造相同；新增工作流改变了调用及反馈机会，预算上限相同不代表计算开销相同。隐藏测试与参考补丁仅由父进程使用，不进入模型请求。

## 实验入口与证据

```powershell
python -m pytest tests/test_compare_workflows.py -q
python -m pytest tests -q
python -m evals.compare_workflows --repeat 3 --output .tmp/evals/localization-workflow-comparison-v1-replay
```

必须使用新目录。入口生成 freeze.json（配置与顺序）、comparison.json（逐次更新聚合与完成状态），并按组保存全部 run_id、补丁、Trace 和独立验收。结束或中断均输出各组独立 summary。只有 completed=true 且 30 次齐全才是完整批次。

Token 汇总区分服务端完整用量和缺失用量，估算回退不能当作实测零成本。耗时包含执行与独立验收；并记录调用数、生成/审查有效次数、保留检查次数、反馈次数、最终公开检查通过次数和失败类型。三个重复共享任务，不能视为 15 个独立缺陷。

## 完整批次结果

2026-10-05 完成全部 30 次，completed=true、stop_reason=null；没有预算终止、超时或缺失用量。测试为 416 passed、1 skipped。共同源码哈希为 `1474f012e83411cfe87293ac6cd1150e9e5bdc1b0fbb4044bb2b0f6c8226202e`；依赖为 openai 3.20.0、rich 15.0.0、python-dotenv 1.2.3。本地模型 Q4_K_M，digest 为 `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`，Ollama 0.34.3。完整配置、任务哈希和执行顺序见 freeze.json。

| 指标 | single-patch | schema-feedback |
| --- | ---: | ---: |
| 独立验收通过 | 12/15（80%） | 15/15（100%） |
| 服务端返回总 Token | 27,552 | 92,844 |
| 模型调用 | 15 | 45 |
| 平均端到端耗时 | 17.82 秒 | 46.36 秒 |
| 中位端到端耗时 | 15.55 秒 | 43.64 秒 |
| 生成检查有效 | 不适用 | 12/15 |
| 审查格式有效且保留检查 | 不适用 | 12/15 |
| 触发一次反馈 | 0 | 3 |
| 最终公开检查通过 | 不适用 | 9/15 |

| 任务 | single-patch | schema-feedback | 新工作流观察 |
| --- | ---: | ---: | --- |
| artifact-routing | 3/3 | 3/3 | 生成检查导入 dataclasses，被当前导入规则拒绝；没有执行检查或反馈 |
| checkout-rounding | 3/3 | 3/3 | 每次保留 4 项检查；排除两个错误金额期望，初次补丁即通过 |
| event-replay | 3/3 | 3/3 | 每次保留 5 项检查；原代码通过、正确补丁反而有 2 项失败，没有触发反馈 |
| job-deadline | 3/3 | 3/3 | 每次保留 6 项检查，初次补丁即通过 |
| pagination-cursor | 0/3 | 3/3 | 每次保留 5 项检查，一次反馈后公开检查及独立验收通过 |

15 对运行的初次补丁提示哈希、证据清单及初次模型输出逐一相同，源码哈希也全部一致，审计见 paired-audit.json。因此本批次的额外通过来自分页任务的后续反馈修复，不能归因于检索变化或更强的初次补丁提示。

新增工作流消耗 3.37 倍 Token、3 倍调用、约 2.60 倍平均耗时；额外消耗 65,292 Token，换来同一分页缺陷的三次额外通过。每个通过运行的 Token 为 2,296 对 6,189.6。这里是本地调用量和时间，未测量电费或 API 费用。

## 检查可靠性与结论边界

artifact-routing 的三次生成均使用 `from dataclasses import dataclass`，违反只允许 unittest 和公开仓库模块的现有规则。补丁仍独立通过，但不能计为自动验证成功，也不能为了提高成绩在批次中途放宽导入限制。

event-replay 的两个被接受断言要求 seen 集合包含裸字符串事件 ID；公开契约仅规定租户范围内去重，并没有约定 seen 的内部表示。正确修复使用 `(tenant, event_id)`，因此这些断言失败。审查格式与引用有效并不代表断言有契约支持，算术校验也无法发现此类语义问题。原代码通过这些检查，现有反馈门槛阻止了它们驱动一次错误修复；最终独立验收仍为通过，公开检查失败记录原样保留。

本批次只能说明：冻结配置下，分页任务的反馈修复可重复；尚不能说明自动检查普遍可靠或该工作流具有足够的成本收益。五项均为已用于开发的合成任务，temperature 0 下三轮输出重复，不是 15 个独立缺陷，也不是留出集泛化验证。暂不将审查工作流推广为默认。

下一步先修正检查的契约支持边界和生成规则一致性，针对事件状态表示、路由导入限制增加失败回归；新版本结果单列。随后再研究仅凭公开证据触发验证的成本优化，并在冻结的真实缺陷留出集验证；不得利用隐藏验收、参考补丁或任务 ID 选择工作流。

## 原始证据保存

本次目录为 `.tmp/evals/localization-workflow-comparison-v1`：freeze.json、comparison.json、paired-audit.json，以及两组各 15 份 report.json、worker-result.json、Trace、补丁和验收输出。该目录被 Git 忽略，提交文档不会保存原始实验；需另行备份整个目录。重跑使用上面的新目录命令，保留此次结果。
