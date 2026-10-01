# P0-2：search_code 工具与关键词证据对照

状态：用户执行新增测试为 17 passed、1 skipped（2.83 秒）；同步 README 行数后，完整回归为 236 passed、1 skipped（44.73 秒）。none/keyword 离线工具链已通过。用户随后授权开发者执行 30 次完整对照，主验收 none 0/15、keyword 1/15，详情见 [完整对照结果](search-code-v1-results.md)。没有新增依赖。向量检索、重排、AST 分块及完整上下文策略仍未实现。

用户离线验收记录：none 汇总 `.tmp/evals/search-code-acceptance/summary-b80429a4e9.md`，keyword 汇总 `.tmp/evals/search-code-acceptance/summary-4ec4d67f88.md`。两者 tool_schema_hash、protocol_prompt_hash 和索引哈希相同，各有一次 search_completed；none 返回 0 字符，keyword 返回 docs/paging.md 的 494 字符证据。这是参考答案辅助的工具链检查，不能计入真实模型效果。

## 首次真实 pilot：证据召回成功但未完成修复

用户于 2026-10-01 在相同源码与默认预算下运行 pagination-cursor 的 none/keyword 各一次。Schema、规范化 Prompt、运行实现哈希和语料索引哈希一致；工作树尚有未提交改动。汇总分别为 `.tmp/evals/search-code-pilot-none/summary-fc2ac1bc9b.md`、`.tmp/evals/search-code-pilot-keyword/summary-288b0206cd.md`。

| 指标 | none | keyword |
| --- | --- | --- |
| 状态 | budget_exceeded | budget_exceeded |
| 主验收 / 源码修改 | 未通过 / 无修改 | 未通过 / 无修改 |
| 累计 Token | 23,600 | 24,390 |
| LLM 调用 | 8 | 7 |
| search_code 调用 | 2 | 2 |
| read_file 调用 | 8 | 3 |
| 端到端秒数 | 45.77 | 28.89 |

keyword 首次查询召回 api.py、docs/paging.md、paging.py、cursor_codec.py，共 1,346 正文字符；第二次查询召回 query.py、paging.py、docs/paging.md，共 1,063 正文字符。因此契约证据已经通过工具结果进入模型上下文，不能说本次失败仍是“没有获取契约”。none 两次均返回空证据，然后读取全部源码与可见测试。

keyword 的读文件数量较少，但同一契约和 paging.py 在两次检索中重复返回，之后又读了已返回的相关源码。当前去重仅限一次搜索的候选片段，不是跨轮历史去重；正文之外的 JSON 元数据也计入模型输入。结合 history 随后续调用重复发送，累计 Token 未降低。不能据此断言模型已经理解或利用契约，也不能确定减少重复后必然修复成功。

两组都在修改之前被下一次请求的累计预算预检阻止。检索接口正常工作，但这一次没有显示主成功率改善或累计 Token 节省。none 先运行、keyword 后运行，加载/缓存条件不同，不能用这两个耗时推断检索加速。

保留失败与当前配置，继续本说明的交替顺序完整开发集对照，观察不同任务的表现。跨轮证据去重、元数据压缩、todo 调度或收尾机制若要优化，应另建配置独立实验，不修改这次 pilot 的解释，也不与关键词收益混算。

## 实现与作用域

工具在 `corecoder/tools/search_code.py`，检索实现在 `corecoder/retrieval/keyword.py`。本轮通过评测器工具工厂接入，没有加入上游全局 ALL_TOOLS，也未改变常规 CoreCoder CLI 的默认工具集合。

```json
{"query": "cursor continuation order contracts", "top_k": 5}
```

结果包含 query、index_hash、results、evidence_chars。每条证据含相对路径、当前行号、片段、当前文件 SHA256、排名分数和截断标记。Agent 可继续用 read_file 阅读完整上下文，然后修改源码。

仅扫描当前任务工作区：Python 限定为 manifest 中允许的源码文件；Markdown 契约可检索。排除 tests、hidden_tests、_target_tests、.git、.eval-logs 等目录，排除符号链接和解析后越界的路径。父目录的参考补丁、evaluation.json、任务 manifest 和目标测试不参与检索。与评测器一样，这些约束不构成恶意代码的宿主沙箱。

使用固定 40 行、无重叠分块，源码与 Markdown 使用同一分块规则。关键词拆分 snake_case/camelCase，中文只做字面二元组匹配，不能把中文语义翻译成英文源码或文档。建议查询使用英文符号和契约术语。

BM25 参数 k1=1.2、b=0.75；相对文件路径和片段共同参与词频，分数相同按路径及起始行排序。完全相同的片段文本去重，再受 top_k 和证据字符预算限制。没有保证“必含契约”的类型配额，以免把额外上下文策略混入关键词实验；契约是否召回必须实测。

索引保存在任务进程内存。每次搜索按内容哈希检查修改、增加和删除，变化后重建小型索引，避免编辑后仍返回旧片段。不是持久化向量库，也不是完整增量解析。语料限制：500 文件、单文件 1 MB、总计 4 MB；超限或非 UTF-8 文件显式报错，不静默忽略。

## 三种配置

| --search-backend | 工具与提示 | 返回证据 | 用途 |
| --- | --- | --- | --- |
| off（默认） | 原有工具及任务提示 | 无 search_code | 保持历史执行入口 |
| none | 添加共同 search_code 与检索提示 | 空列表 | 空证据控制 |
| keyword | 与 none 相同的 Schema 与提示 | BM25 关键词片段 | 关键词配置 |

none 与 keyword 都检查同一工作区并构建同一索引，只有 keyword 执行排名并返回证据。后端名称只写入配置和 Trace，不进入工具描述或返回字段。原生 read/glob/grep 在两组均保留，任务不被强制禁止手动探索。

共有提示要求先使用 search_code 查找代码与文档契约，读取相关完整文件后编辑；没有自动把任务描述作为检索结果塞入上下文，也没有隐含参考答案。none 返回空证据后允许继续使用原有工具。

`--search-max-chars` 默认 6,000，范围 256–20,000；top_k 默认 5，范围 1–10。字符预算按片段正文计，不包含 JSON 元数据，也不等于精确 Token 上限。真正模型用量仍由 LLM usage 累计计入任务预算。全文截断可能发生在行中，truncated=true；引用的 end_line 是实际返回内容所在行。

## 记录与公平条件

每次搜索输出 search_completed 事件：查询、后端、选中证据、丢弃理由、证据字符数、语料文件数、索引哈希、扫描/构建/总耗时与缓存命中。完整片段保存在正常 tool_finished 中，控制组不会在 Trace 中偷偷返回正文。索引耗时在总工具耗时内，详细耗时不能与 tool_seconds 再次相加。

Worker 保存原始 prompt_hash 和 protocol_prompt_hash。原始系统提示含每次独立工作区路径，因此原始哈希可能不同；protocol_prompt_hash 用统一占位符替换工作区路径，供同任务的 none/keyword 比较。工具 Schema 哈希也应相同。不同任务描述不同，不能要求跨任务 Prompt 哈希相同。

搜索查询是 Agent 的决定。对照测量的是在共同接口下“提供关键词证据”对整体策略执行的影响，不是给定同一查询时的纯检索排名效果。文件检索 Recall/MRR 的固定查询离线评估尚未实现。

本轮没有提高 Token/轮次预算、改变主成功标准、添加收尾兜底或反思步骤。历史 localization-v1-baseline 没有新工具/提示，因此不能直接替代 none 对照。none/keyword 必须在当前同一版本下重跑；先运行一个 pilot 确认模型确实调用工具。

## 用户测试步骤

在项目根目录、corecoder 环境执行。以下是预期，不是已执行结果。

### 1. 新增测试与完整回归

```powershell
python -m pytest tests/test_search_code.py -q
python -m pytest tests -q
```

新增测试覆盖引用、源码/契约检索、控制组 Schema、无匹配、范围与符号链接、编辑后的索引更新、分块、正文预算、去重、参数、确定性排名、Trace、默认工具兼容以及两个后端的真实 Worker 离线集成。Windows 若没有创建符号链接权限，对应测试会 skip；其他项应通过。

### 2. 离线工具链验收

```powershell
python -m evals --suite evals/fixtures/localization-v1 --mode scripted --task pagination-cursor --search-backend none --output .tmp/evals/search-code-acceptance
python -m evals --suite evals/fixtures/localization-v1 --mode scripted --task pagination-cursor --search-backend keyword --output .tmp/evals/search-code-acceptance
```

两次都应 passed，且 Trace 包含 search_completed。scripted 会先用固定 contract 查询测试工具，再应用参考修复；它不代表真实模型效果。对照的 tool_schema_hash 与 protocol_prompt_hash 应相同，none 的 evidence_chars=0，keyword 应有文档契约证据。

### 3. 真实单项对照

```powershell
python -m evals --suite evals/fixtures/localization-v1 --mode live --task pagination-cursor --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend none --output .tmp/evals/search-code-pilot-none
python -m evals --suite evals/fixtures/localization-v1 --mode live --task pagination-cursor --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --output .tmp/evals/search-code-pilot-keyword
```

成功或失败均保留。检查是否使用了 search_code、是否召回并阅读 docs/paging.md、是否同时修复两处实现、用量及预算终止原因。没有调用工具时不能声称检索已经提供收益。遇到基础设施问题先修复，修复后两组使用同一代码版本重新记录。

### 4. 完整探索性对照

前述步骤确认工具链可靠后，提交或冻结代码，保留默认预算。建议交替配置顺序，减少所有 none 先运行、所有 keyword 后运行造成的加载/缓存偏差。下面使用 PowerShell（不是 cmd），共运行 30 项任务：

```powershell
foreach ($experimentRound in 1..3) {
    $experimentBackends = if ($experimentRound % 2 -eq 1) { @('none', 'keyword') } else { @('keyword', 'none') }
    foreach ($experimentBackend in $experimentBackends) {
        python -m evals --suite evals/fixtures/localization-v1 --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend $experimentBackend --output ".tmp/evals/search-code-v1/$experimentBackend/round-$experimentRound"
    }
}
```

每个 CLI 批次 repeat=1，重复轮次由输出目录标识，各配置共 5×3 项。模型修复失败返回码 1，循环仍继续并保留汇总。不要启用“遇到非零退出码就终止”的终端策略。顺序交替仍未完全控制缓存，结果应说明这个限制；5 项开发任务仅用于探索，不能作真实仓库泛化结论。

把 6 份 summary 路径发给开发者，再汇总主成功率、全部任务 Token、工具/检索时间、契约引用与失败变化。不要提前假设 keyword 必须更好；如果需要调参，建立新的开发配置并完整保留旧结果。原始实验目录被 Git 忽略，需要另行备份。
