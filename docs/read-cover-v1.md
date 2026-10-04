# read-cover-v1：完整读取覆盖搜索正文

更新：2026-10-03。**本轮干预已在真实 pilot 中触发，缩短了相同请求中的输入估算；尚无修复成功率或累计 Token 收益证据。** 默认策略仍为 none。

## 实现与边界

新增 `--context-policy none|read-cover`。read-cover 仅允许关键词检索且 search-history=full，避免混合两个去重干预。工具 Schema、Prompt、任务、权限、检索选择和预算保持不变。

ScopedTool 为成功读取生成内部凭据：相对路径、原始字节 SHA256、完整行与实际响应。只接受与整个文件编号正文完全一致的读取；部分读取、错误、脱敏后不一致、非严格 UTF-8 等情况不授权替换。

每轮请求时，若旧搜索片段已被**后续完整读取**覆盖，且该读取的 assistant 调用与 tool 响应仍存在、路径一致、当前文件哈希与两份证据版本相同，便在请求视图中将搜索正文替换成 `retained_read_file` 引用，保留路径、行号、哈希、评分及读取 tool_call_id。同时检查实际片段是对应完整行的前缀，支持截断搜索片段。只有整个修改后的搜索消息估算更短时才采用；引用元数据开销过大则保留原文。

**原始历史不修改。** 文件变化、删除、读取被压缩/截断或原读取从历史消失，下一轮自然恢复原搜索正文；不自动刷新旧证据。该策略不合并多个读取，不优化读取早于搜索的情形，不改变 CoreCoder 的压缩器。压缩器仍处理原始历史，其调用和用量继续计入预算。完整读取须保留在下一轮模型请求中，才允许替换旧正文。

实现位于 evals/context_policy.py，作为评测适配层中的实验策略；暂未推广到默认交互式 Agent。canonical history 与原始工具 Trace 保留完整证据，便于审计。

## 新增开销观测

BudgetLLM 每次尝试调用前记录 request_preflight，包括 system、user、assistant、search_code、read_file、other_tool 的消息估算、工具 Schema 估算、累计用量、剩余预算及输出预留。分类求和与原有估算规则一致，不改变预算口径；记录被预算拦截、尚未发送的请求。

budget_blocked 区分累计预检、上下文窗口预检和返回 usage 超预算。context_organized 记录本次视图的替换项数、省略字符、估算输入缩减和未获益消息数。它描述每轮视图，不能将重复出现的项数当成独立片段数；被拦截请求的缩减不计作已发送输入减少。

这些是近似估算，不是提供商逐组件 Token 计费。角色分类尚不细分每个 JSON 字段的正文/元数据。提供商实际 usage 单独记录，不能将两种数字混用。

## 验证

- 新增 14 项测试：有效覆盖、原历史保留、文件变化/删除、历史截断、路径匹配、部分/失败读取、引用开销门槛、真实 Agent 请求视图、配置隔离及预算日志。
- 全量回归：**269 passed、1 skipped，44.35 秒**；Windows 符号链接测试跳过。Ruff 与 git diff --check 通过。
- 四次 pilot 源码哈希一致：`26f91787cfcb818bcd98b0e3471f21c26fa0a54aa77dc284ac88f68066d9c1e6`。同任务两组的 fixture、grader、manifest、工具 Schema、规范化 Prompt 哈希一致；配置仅 context_policy 不同。

## 四次真实 pilot

模型 Ollama qwen3.5:27b，reasoning_effort=none、temperature=0；Token 30,000、输出 2,048、12 轮、估算上下文 16,000、Worker 180 秒、测试 15 秒、搜索正文 6,000 字符。顺序为分页 none → read-cover，租约 read-cover → none。每配置每任务仅一次，无选择性重跑，不作为完整效果实验。

| 任务/策略 | 状态 | 实际总 Token（输入/输出） | LLM 调用 | 搜索/读取 | 已发送请求中覆盖触发轮数 |
| --- | --- | --- | --- | --- | --- |
| pagination / none | budget_exceeded | 27,409（26,386/1,023） | 7 | 2/4 | — |
| pagination / read-cover | budget_exceeded | 27,483（26,808/675） | 8 | 1/3 | 5/8 |
| lease / none | budget_exceeded | 26,715（25,871/844） | 6 | 1/14 | — |
| lease / read-cover | budget_exceeded | 26,924（26,129/795） | 5 | 3/14 | 1/5 |

两组主验收均 0/2，四次均无源码修改、目标失败、回归通过。无基础设施故障或 usage 缺失。仍不能称为有效修复优化，暂不扩大到 30 次运行。

分页覆盖组已发送请求的估算缩减依次为 0、0、0、125、125、197、197、282，合计 926；租约为 0、0、0、0、604，合计 604。这是**同一实际请求相对其原始历史视图**的估算差值，不是两组实际 Token 差值。租约最多一轮替换 15 项，来自多个搜索结果；不等于 15 次工具调用。

两组模型选择的查询、工具批次、计划和轮数不同。租约覆盖组在完整读取前搜索了三个不同入口，控制组只搜索一次，不能把该行为变化全归因于覆盖策略——此前尚无覆盖正文。温度为零仍有轨迹波动。覆盖组累计用量略高，样本不足以判断统计显著变化，更不能外推到真实仓库。

## 为什么仍然预算终止

| 任务/策略 | 最后尝试输入估算 | 工具 Schema 估算 | 剩余预算 | 输入 + 输出预留 |
| --- | --- | --- | --- | --- |
| pagination / none | 6,353 | 1,490 | 2,591 | 8,401 |
| pagination / read-cover | 4,826 | 1,490 | 2,517 | 6,874 |
| lease / none | 6,844 | 1,490 | 3,285 | 8,892 |
| lease / read-cover | 7,212 | 1,490 | 3,076 | 9,260 |

四次均因累计预算预检停止，而非 16,000 上下文窗口溢出。分页控制组最后消息中 assistant 估算 1,643、搜索 1,427、读取 423；租约控制组分别为 1,206、1,499、1,088。历史与 Schema 反复参与请求，省去少量重复片段不足以使剩余预算容纳下一轮。首次请求本身约 2,470–2,500，不应将全部开销都归因于代码正文。

## 产物与复跑

- [pagination none](../.tmp/evals/read-cover-v1/pilot/pagination-cursor/none/summary-5d1b95403e.md)
- [pagination read-cover](../.tmp/evals/read-cover-v1/pilot/pagination-cursor/read-cover/summary-9a7500c966.md)
- [lease read-cover](../.tmp/evals/read-cover-v1/pilot/lease-lifecycle/read-cover/summary-dd425b1680.md)
- [lease none](../.tmp/evals/read-cover-v1/pilot/lease-lifecycle/none/summary-8c309fdd6f.md)

同名 JSON 保存完整报告。Trace 中 request_preflight 与 context_organized 对应每次尝试，llm_started 区分真正提交的请求。原始目录被 Git 忽略，需单独备份。

```powershell
python -m pytest tests/test_read_cover.py -q
python -m pytest tests -q
python -m evals --suite evals/fixtures/localization-v1 --task pagination-cursor --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --search-history full --context-policy none --output .tmp/evals/read-cover-v1/pilot/pagination-cursor/none
python -m evals --suite evals/fixtures/localization-v1 --task pagination-cursor --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --search-history full --context-policy read-cover --output .tmp/evals/read-cover-v1/pilot/pagination-cursor/read-cover
```

新实验请使用新输出目录；未通过的 CLI 返回码 1 不等于基础设施故障。

下一步先分析“修改前消耗”：计划消息、额外检索、分散读取和工具 Schema 的重复携带。仅定义一个新的干预或预算敏感性诊断，保留本轮默认预算记录；不通过提高预算覆盖当前负面结果，也不把估算缩减写成实测 Token 节省。
