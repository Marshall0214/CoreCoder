# Harness² 50 项重跑：成本与执行行为复盘

分析对象：`D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106`。

本次只读已结束实验的报告、逐调用 Trace、反馈轮次和验证回执；未调用模型、未联网、未重跑测试、未修改运行时代码。可复算脚本为同目录 `cost_analysis.py`，完整机械聚合为 `cost-analysis.json`。未发现适用于仓库和本目录祖先路径的 AGENTS.md。

## 1. 结论

本批 50 项、200 次修复执行、200 次策略编辑全部完成 PPC 外层流程，最终独立验收 25/50。实际新模型调用 3,417 次，墙钟 57,122.274 秒，即 15 小时 52 分 2 秒。原始 Agent 24/50、旧 Harness² 27/50 均为完整历史结果复用，不是本次重新运行。

主要成本不在初始定位，而在反馈修正：1,181 次反馈请求中 1,115 次（94.41%）补丁被拒绝，工作区哈希不变。反馈阶段已知原生 Token 至少 38,251,783，占本次逐调用已知 Token 下界的 63.97%。这 1,115 次没有改变候选的尝试消耗至少 37,169,914 Token。单纯给更多轮次没有解决上下文/补丁格式/反馈验证的问题。

另一个需要优先修复的闭环故障是：**本批 35 次成功应用反馈补丁，随后 35 次公开验证全部因 `SandboxError: sandbox_invalid_result` 被阻塞**。不能把“补丁应用成功”当作“公开测试失败”或“模型修改没有作用”；这里没有产生可判断修复效果的公开测试结果。外层 PPC 的 errors=0 不代表其内部没有基础设施失败。

## 2. Token 原摘要漏加了多少

| 口径 | 已知 Token 下界 | 说明 |
|---|---:|---|
| comparison.json 的原口径 | 30,859,536 | 仅把完整用量的 35 个任务相加；另 15 个任务只要有一个阶段未知，整项被排除 |
| 对所有已知完整 phase 相加 | 56,996,965 | 加回上述不完整任务中已知的其他阶段 |
| 对逐调用 Trace 的已知原生 usage 相加 | **59,796,366** | 再加回 30 个不完整反馈阶段中已知的调用 |

**真实完整总量仍为未知**：存在 30 次 `llm_failed`，原生输入/输出 usage 都是 null。不能补零，不能拿任意两个下界之比当作真实成本比。59,796,366 可以作为更紧的已知下界，不应覆盖原始报告，也不能变成“本次完整总 Token”。

机械口径：每个 candidate、feedback、editor 文件夹只读一次本身的 Trace；对 `llm_finished` / `llm_failed` 中两项均为整数、`usage_known != false` 的原生输入输出求和。共 3,387 个已知调用、30 个未知调用，合计 3,417。各 phase 小计与原指标、模型调用数均已交叉校验。

| 阶段 | 调用 | 已知输入 | 已知输出 | 已知合计下界 |
|---|---:|---:|---:|---:|
| candidate 初始修复 | 1,059 | 3,729,979 | 71,035 | 3,801,014 |
| feedback 公开反馈修正 | 1,181 | 37,605,254 | 646,529 | 38,251,783 |
| editor 提议/合成/经验提取 | 1,177 | 17,598,753 | 144,816 | 17,743,569 |
| 合计 | **3,417** | **58,933,986** | **862,380** | **59,796,366** |

失败的 25 项用了 49,622.485 秒（占 50 项 result.seconds 之和的 88.09%）、2,761 次调用、1,123 次反馈请求；通过的 25 项用了 6,706.583 秒、656 次调用、58 次反馈。因 inv/dom 并发，逐调用时长之和和反馈执行时长之和不能当作墙钟时间。

## 3. 反馈轮次到底做了什么

| 尝试结果 | 次数 | 解释 |
|---|---:|---|
| invalid_patch_schema | 839 | JSON 层级、字段名或类型不符合执行器要求 |
| anchor_not_found | 193 | 唯一匹配原文不存在 |
| syntax_error | 65 | 补丁静态语法检查拒绝 |
| no_change | 17 | 未产生有效改变 |
| anchor_ambiguous | 1 | 原文不是唯一匹配 |
| applied | 35 | 文件发生改变；随后公开验证阻塞，不等于正确 |
| provider_failed | 30 | 本地 provider 请求失败，usage 未知 |
| not_applied | 1 | 超时/截止后没有应用返回结果 |
| 合计 | **1,181** | 包含所有请求，不丢弃无效尝试 |

200 次 feedback 执行的结束状态：87 `ready_for_review`（全部 0 轮，是初始候选已通过公开检查）、46 `feedback_round_limit`（全部跑满 20 轮，合计 920 次但零应用）、36 `validation_blocked`（35 个新补丁验证结果无效，1 个初始验证 sandbox_timeout）、30 `local_provider_failed`、1 `task_timeout`。

因此，本批没有一次“经过至少一轮反馈修改后，新通过公开验证”的完成记录。这里同时存在模型输出问题和验证基础设施问题，不能仅归因于模型推理能力或 Harness² 搜索无效。

## 4. 具体 Trace 证据

### 证据 A：Click 环境变量，20 次补丁格式失败且工作区不变

目录：

`D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-flag-envvar/executions/issue-cc-agg1/click-flag-envvar/agg1/feedback/`

- `trace.jsonl` sequence 1：`request_estimate=126291`、`provider_context_tokens=65536`、`context_preflight_enforced=false`。这是执行器估算，不是模型真实 tokenizer 计数。
- sequence 3：原生 `prompt_tokens=32770, completion_tokens=10012`。
- `report.json`：20 次请求，每次原生输入都是 32,770，20 次全部 `invalid_patch_schema`，`applied_patches=0`，初始和最终候选哈希相同。
- `rounds/004/response.txt` 的根字段为 `edit`，每项使用 `path`；执行器契约要求根字段 `edits`、每项 `file`。该响应还修改 `types.py/get_metavar`，与当前环境变量 flag 问题不一致。
- `rounds/004/messages.json` 仍完整保存了系统格式约束、当前源码和公开反馈，因此保存记录不是“压缩时没有记录正文”；但这些内容服务端实际保留了哪部分，不能只靠这个文件推断。

全批反馈 1,181 次请求中，1,168 次估算超过声明的 65,536 上下文；1,151 次有已知原生 usage，其中 1,138 次的原生输入都恰为 32,770。这是上下文有效性的重要风险信号。主分析另从本机 Ollama server.log 核对到了 `truncating input prompt` 警告；服务端究竟保留/丢弃哪个片段仍需单独验证。

### 证据 B：Click help，反馈补丁成功应用却未得到测试结果

目录：

`D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-help-eagerness/executions/issue-cc-agg1/click-help-eagerness/base1/feedback/`

- `report.json`：第 1、2 轮 schema 被拒；第 3 轮 `patch_status=applied`，修改 `src/click/parser.py`，工作区哈希由 `d2cf0e...` 变成 `948e0c...`。
- `rounds/003/validation/report.json`：`status=blocked`，`infrastructure_error="SandboxError: sandbox_invalid_result"`，`public_checks=null`；未产生公开测试结果。
- 第 3 轮随后结束整个 feedback，状态是 `validation_blocked`。不能解释成“第 3 轮已经测试失败所以放弃”。

`cost-analysis.json.blocked_validation_records` 包含全部 36 个阻塞验证回执的路径、候选哈希和错误类型，方便进一步定位 sandbox 结果文件协议。

### 证据 C：Boltons split-zero，四种指导各跑满 20 次仍没有有效编辑

目录：

`D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/boltons-split-zero/executions/issue-cc-agg1/boltons-split-zero/`

- base1、inv1、dom1、agg1 的 `feedback/report.json` 均为 `feedback_round_limit`。
- 合计 80 次请求全部被拒、0 次成功应用，最终独立验收失败。
- 任务整体 148 次模型调用，已知总 Token 3,447,287（该任务 usage 完整）、2,737.531 秒。

这证明扩展策略搜索会重复承担底层反馈入口的相同失败，不是四种指导自动带来四次独立有效修复。

## 5. 仍有次要瓶颈

初始 candidate 200 次执行中，140 次产生候选，54 次重复动作停止、3 次连续错误停止、3 次步数到限。指导改变并没有彻底消除读取循环。

策略编辑器仍有重复证据读取：200 个 editor 中后续完全相同范围读取 215 次；总请求字符 3,644,499，按每个 editor 同一 path+SHA 的字符区间并集去重后为 2,213,121，重叠 1,431,378 字符（39.28%）。这不是 Token 计数，也不能直接当作可节省的 Token，但表明 recent-pages 不等于避免重复读取。例：`click-style-color-validation/editors/call-001/reader-report.json` 20 次请求、17 次证据读取，其中 11 次完全相同范围，96,358 请求字符中 71,679 重叠。

## 6. 建议先后顺序

1. 先修独立公开验证的结果协议：解释并修复全部 35 次 applied 后 `sandbox_invalid_result`，使用已留存补丁做零模型回放验收，确认正常/失败/超时结果都能被解析；不要让优化器修改评分。
2. 修反馈上下文接口：不再无差别附带所有 allowed 文件；优先系统补丁 schema、当前错误和目标符号完整源码，按需读依赖，建立实际发送与服务端有效上下文的可核对 receipt。先用少量代表任务证明不再截断且反馈能到达模型，再谈通过率。
3. 保留最多 20 轮的用户设定，但每次拒绝必须提供可执行、短而位于有效上下文内的格式/锚点反馈；记录 no-change 原因，显式切换修复行动。当前证据支持修接口，不支持再加大轮次。
4. 暂缓扩大 Harness² 权限。当前 costly search 乘的是一个损坏的反馈入口；先让单次“改→验→反馈→再改”可靠工作，再用相同冻结案例比较是否值得逐任务搜索。

上述是事后发现与下一轮建议，不修改本轮实验结论、不补算不存在的成功，也不把历史控制组成本当作零。
