# 真实任务搜索历史对照 v1

## 本次工作

将已有搜索历史去重接入 `python -m evals.real_tasks --search-history full|deduplicate`，默认仍为 full。新增 `python -m evals.compare_real_history`，执行交替顺序的同任务对照，冻结代码、依赖、任务、检查、模型、Prompt、工具接口与预算，并保留全部运行结果。

去重只将仍在模型历史中的相同代码证据替换为引用，不删除首次证据，也不把省出的空间用于召回额外代码。现有测试覆盖证据变化与历史压缩后的重新返回，本次不改变检索排名算法。

## 固定条件

任务：已准入的真实开发候选 `click-flag-envvar`，公开问题与独立验收保持不变。该案例已经查看官方修复，不能计入留出集。

模型：本地 Ollama qwen3.5:27b，reasoning_effort none、temperature 0。运行前以空 Prompt 预加载模型；预加载不属于修复模型调用。每次运行前后核对已加载模型 digest：

`7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`

实现摘要：`9ea7b9b3e1a7516f461a76503a9016f53064e80280d9b41142b0fe663823fb54`。

预算固定为 12 轮、30,000 Token、16,000 上下文估计窗口、2,048 输出预留、180 秒 Worker 超时、15 秒单组检查超时；关键词检索每次证据正文最多 6,000 字符。两组 RunConfig 唯一差异是 search_history，Prompt 和工具 schema 摘要一致。

配对顺序：full → deduplicate；deduplicate → full；full → deduplicate。每次使用新工作区，去重状态不跨运行共享。源码、模型或协议漂移会停止整个批次并保留部分结果，不选择性补跑失败样本。

## 实测结果

2026-10-05，三组配对、共六次真实模型运行，提供方 usage 均可用。

| 指标 | full | deduplicate |
| --- | --- | --- |
| 通过独立验收 | 0/3 | 0/3 |
| budget_exceeded | 3/3 | 3/3 |
| 模型调用总数 | 15 | 15 |
| 输入 Token 总数 | 73,551 | 66,765 |
| 输出 Token 总数 | 1,000 | 1,015 |
| Token 合计 | 74,551 | 67,780 |
| 耗时均值 / 秒 | 17.3140 | 16.9692 |
| 进入编辑的运行 | 0/3 | 0/3 |
| 实际源码变更 | 无 | 无 |
| 去重引用命中总数 | 0 | 6 |
| 省略重复证据正文字符总数 | 0 | 9,303 |

| 配对 | full Token | deduplicate Token | 两组结果 |
| --- | --- | --- | --- |
| 1 | 25,132 | 22,431 | 均预算不足 |
| 2 | 25,538 | 22,430 | 均预算不足 |
| 3 | 23,881 | 22,919 | 均预算不足 |

本批次去重组 Token 合计低 6,771，约 9.1%。三次去重均命中 2 处引用、省略 3,101 字符，确认策略实际触发；字符数不是 Token 数，二者分开报告。这里的 Token 差异包含 Agent 后续行为变化，不是固定输入回放下的纯压缩测量。

六次均只完成 5 次模型调用：两次 search_code，随后 read_file 或 grep，没有编辑或可见测试调用。第 6 次请求因估计请求加输出预留超过剩余累计预算而被阻止。目标检查均失败，Controls 均通过。

结论：在这个开发案例上，去重减少了重复证据和观测到的 Token 消耗，但没有改变修复结果。单任务三组配对不足以推广为整体成功率或性能结论；即便 temperature 0，各次查询和读取位置仍有差异。耗时受缓存及运行环境影响，仅作记录。

## 证据与验证

`.tmp/real-defects/history-comparison-v1/freeze.json` 保存配置、执行顺序和冻结摘要；`comparison.json` 保存 completed true、两组全部报告、聚合值、模型 digest 以及逐次 Trace 指标。full、deduplicate 子目录分别保存独立源码、任务输入、日志、评分与 trace.jsonl。以前的单次冒烟未混入此批次统计。

相关测试 22 passed；全量回归 504 passed、1 skipped；修改文件 Ruff 检查通过。新增测试验证真实任务 CLI 将策略传入 Worker、对照只改变历史策略、交替顺序及模型版本变化时停止并保留结果。

## 复跑

先确保本地 Ollama 模型已加载。对照工具当前限定上述模型与预算，并要求运行前后能够从 /api/ps 确认模型 digest；模型未加载时应先预加载，不跳过版本校验。PowerShell 中可执行：

```powershell
$body = @{ model = 'qwen3.5:27b'; prompt = ''; stream = $false; keep_alive = '30m' } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:11434/api/generate -Method Post -ContentType 'application/json' -Body $body
python -m evals.compare_real_history --admission .tmp/real-defects/crossfile-admission-v2/admission.json --output .tmp/real-defects/history-comparison-reproduction --repeat 3
python -m pytest tests -q
```

output 必须是新目录。对照退出码 0 表示批次按冻结协议完成，不表示 Agent 修复成功；具体修复结果以 comparison.json 中 accepted 为准。

单独验证去重入口：

```powershell
python -m evals.real_tasks --admission .tmp/real-defects/crossfile-admission-v2/admission.json --mode live --search-backend keyword --search-history deduplicate --output .tmp/real-defects/history-deduplicate-pilot
```

## 下一步

保持任务、模型和总预算不变，比较更短的检索返回上限（例如 6,000 与 3,000 字符），观察减少单次上下文能否给后续编辑留下调用空间，同时检查遗漏证据及独立验收。此参数选择只用于开发，不借目标验收内容构造模型提示；默认策略保持不变。扩充与冻结留出任务仍待完成。
