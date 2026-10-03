# search-history-v1：跨轮证据去重

本轮只改变重复 search_code 正文的返回方式，不改变 BM25、任务、工具 Schema、Prompt、预算、评分或 read_file。用户授权开发者执行代码验证与真实对照，30 次运行已完成。**真实任务未触发去重，因此本轮不能估计去重对修复成功率或 Token 的效果。**

`--search-backend keyword --search-history full` 是全文控制，`--search-history deduplicate` 是去重配置。full 为默认，deduplicate 只允许与 keyword 配合。工具描述与生成参数相同，模式名称不进入工具返回或提示。

同路径、文件 SHA256、起始/结束行及实际片段文本都相同，且原始工具结果仍在模型的 tool 历史中时，重复项保留引用元数据，正文变为空，增加 `reference: previous_search_result`。第一次命中照常返回正文；文件变化时重新返回。截断片段不能代替未送达的完整片段。

工具实例按任务独立，Agent 每轮请求前同步仍保留的工具消息；上下文压缩或 reset 丢掉原始结果时，失效的引用记录清除，下一次返回全文。仅保留引用消息不足以延续原始正文。没有替代摘要、没有修改历史消息本身。

排名、top_k、单次精确文本去重及逻辑证据预算在两组相同。重复片段仍占用原逻辑字符配额，不能用省略出的空间召回额外片段；`evidence_chars` 记录实际正文长度。search_completed 追加 reference_hits、omitted_chars、logical_evidence_chars、response_chars，省略字符不是精确 Token 节省；引用 JSON 自身也有开销。

此机制只作用于重复搜索，不去重 read_file，不要求模型改变工具调用顺序；首次搜索没有任何去重收益。search-code-v1 中关键词组 15 次共 16 次搜索，因此当前样本存在干预机会不足的风险。必须记录实际引用命中次数，不能只根据开关开启就声称收益；不为增加去重命中而修改任务或 Prompt。

## 验证与对照协议

新增 tests/test_search_history.py 覆盖重复引用、默认全文、版本失效、历史压缩、引用不能保活、截断、任务隔离、预算选择一致、配置及真实 Agent 循环。已有 README 行数同步更新。

真实实验为 5 个开发任务 × 3 次 × 2 配置，共 30 次；第 1/3 轮 full → deduplicate，第 2 轮反序。关键词检索、temperature=0、reasoning_effort=none、Token 30,000、输出 2,048、12 轮、上下文估算 16,000、Worker 180 秒、测试 15 秒、正文字符预算 6,000 均保持一致。

PowerShell 复跑方式：

```powershell
foreach ($experimentRound in 1..3) {
    $experimentHistories = if ($experimentRound % 2 -eq 1) { @('full', 'deduplicate') } else { @('deduplicate', 'full') }
    foreach ($experimentHistory in $experimentHistories) {
        python -m evals --suite evals/fixtures/localization-v1 --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --search-history $experimentHistory --output ".tmp/evals/search-history-v1/$experimentHistory/round-$experimentRound"
    }
}
```

记录主成功率、全部运行 Token、预算终止、候选通过、去重触发运行数/引用项数/省略字符及响应字符。若无引用命中，本轮不能估计去重效果，需改用冻结的固定多查询离线诊断确认机制，真实任务结果照实报告。原始 search-code-v1 不替代当前全文共同版本基线。

5 个独立任务的重复结果属于探索性数据，不能推出统计显著或真实仓库收益。完整失败保留；不追加选择性重跑。索引刷新和旧历史仍计入时间及用量；去重并不消除已经发送过的历史开销。原始产物需要另行备份，不随文档提交保存。

## 已执行的验证

- 去重与检索测试：29 passed、1 skipped；全量回归：248 passed、1 skipped（45.49 秒）。跳过项为 Windows 符号链接测试。
- 修改文件 Ruff 检查通过；README 中英文代码行数同步。
- 同任务 6 次运行的 fixture、grader、manifest、protocol_prompt 和 tool_schema 哈希各自一致；30 次使用同一源码哈希，无基础设施故障或缺失 usage。

## 真实对照结果（2026-10-01）

| 指标 | full | deduplicate |
| --- | --- | --- |
| 正式验收通过 | 2/15 | 1/15 |
| 候选补丁独立测试通过 | 2/15 | 1/15 |
| budget_exceeded | 11/15 | 11/15 |
| 正常结束但 failed_verification | 2/15 | 3/15 |
| 平均 / 中位数 Token | 25,376.5 / 25,895 | 24,907.6 / 25,449 |
| LLM 调用总数 | 107 | 106 |
| search_code / read_file 调用 | 15 / 97 | 15 / 99 |
| 去重触发运行 / 引用项 | 0 / 0 | 0 / 0 |
| 省略正文字符 | 0 | 0 |
| 搜索响应字符合计 | 41,781 | 41,784 |
| 平均 / 中位数端到端秒数 | 46.76 / 46.54 | 45.85 / 45.96 |

full 输入 372,535、输出 8,113，共 380,648 Token；deduplicate 输入 365,478、输出 8,136，共 373,614 Token。费用未知。两组均每次运行只搜索一次，首次响应没有去重干预。平均用量、耗时和成功率差异是本轮观测，**不能归因于去重，不能描述为节省或退化**。temperature=0 仍观察到调用及补丁波动；批次顺序也不能完全控制缓存、加载和宿主负载。

| 任务 | full 三次状态 | deduplicate 三次状态 |
| --- | --- | --- |
| artifact-routing | 预算、预算、预算 | 预算、预算、预算 |
| checkout-rounding | 通过、通过、预算 | 预算、通过、预算 |
| event-replay | 预算、预算、预算 | 预算、预算、预算 |
| job-deadline | 预算、预算、预算 | 预算、预算、预算 |
| pagination-cursor | 预算、验证失败、验证失败 | 验证失败、验证失败、验证失败 |

成功均来自结算任务，两处舍入实现同时修复且正常收尾；分页正常结束仍未满足独立目标测试。22/30 次受预算预检限制；当前实际用量低于 30,000 也可能停止，因为下一轮输入估算及预留输出须放入剩余预算。没有因候选通过而提升正式成功数，也未选择性重跑失败。

首批 full round-1 结束后，调度脚本误把 CLI 的普通未通过退出码 1 当作执行故障而暂停；核实五份报告完整后，仅继续剩余五批。源码、顺序、评分和已有运行均未改变。复跑脚本应允许退出码 1，检查报告完整性，其他退出码或基础设施故障再停止。

## 固定查询机制诊断

真实运行结束后追加**离线、事后诊断**，不调用模型、不计入修复成功率。使用 pagination-cursor 缺陷 workspace，固定查询 `cursor pagination contract`、top_k=5、max_chars=6,000：首次查询 → 保留原 tool 消息并重复查询 → 清空 tool 历史再次查询。两组片段路径和行号保持相同。

| 步骤 | full 响应字符 / 正文字符 | deduplicate 响应字符 / 正文字符 | 引用项 |
| --- | --- | --- | --- |
| 首次 | 2,327 / 1,346 | 2,327 / 1,346 | 0 |
| 保留历史后重复 | 2,327 / 1,346 | 1,091 / 0 | 4 |
| 移除历史后再次查询 | 2,327 / 1,346 | 2,327 / 1,346 | 0 |

重复响应净减少 1,236 字符；元数据引用仍有开销，不等于 1,346 个 Token，也不证明修复收益。历史移除后完整正文恢复。原始记录见 `.tmp/evals/search-history-v1/diagnostic.json`；自动化复现入口为 `python -m pytest tests/test_search_history.py -q`，覆盖固定重复查询、文件版本、截断与 Agent 历史失效等规则。

## 版本、产物与下一步

实验源码哈希：`4f090ab51600067e44d73c47cd2d3d2ae807fc16cc39a54a5eb3646d94069a68`。Git 基点 `4e6a41d5ef5750e40253c6f7c4d0cabd7a5e05e9` 加本轮未提交代码；各报告保存实际工作树状态。工具 Schema 哈希 `2f3d66608b338573dabce6e2e82d634328246e10252891a56ad752821b37d5aa`。Python 3.11.16，openai 3.20.0，Ollama 0.34.3，Qwen 27.8B Q4_K_M，实际加载上下文 32,768。模型摘要、提示及任务哈希详见各 report.json。

六份汇总，JSON 与 Markdown 同名：

- [full round-1](../.tmp/evals/search-history-v1/full/round-1/summary-756ebccf35.md)
- [deduplicate round-1](../.tmp/evals/search-history-v1/deduplicate/round-1/summary-9cf4771671.md)
- [deduplicate round-2](../.tmp/evals/search-history-v1/deduplicate/round-2/summary-706167707e.md)
- [full round-2](../.tmp/evals/search-history-v1/full/round-2/summary-53935005dc.md)
- [full round-3](../.tmp/evals/search-history-v1/full/round-3/summary-48c6b6833c.md)
- [deduplicate round-3](../.tmp/evals/search-history-v1/deduplicate/round-3/summary-0c3b14366a.md)

去重保留为可选机制，默认 full。下一步优先从预算预检及消息增长 Trace 定义单独的上下文开销诊断；若研究真实去重效果，需预先冻结有自然重复检索需求的独立任务集。不要通过强制模型重复搜索改变现有任务来制造收益，也不要把本轮差异写成简历提升比例。
