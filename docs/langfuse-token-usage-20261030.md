# 本地模型 Token 统计修复与验收

**结论：真实 Ollama 响应、本地事件/报告、Langfuse 三处用量一致。**一次 Qwen3.5 27B 无思考推理，输入 **938**、输出 **89**，合计 **1,027 Token**；云 API 费用 **$0**，本地算力/电力成本未核算。此为合成任务的工程验收，不是新的修复率实验。

[查看真实模型 Trace](http://127.0.0.1:3300/project/corecoder-issues/traces/449dfc3d57dcaee605bb3eea1612ebae)。旧脚本 Trace 没有实测用量，不回填虚构 Token。

## 修复内容

| 问题 | 当前处理 |
| --- | --- |
| 缺失用量默认填 0 | Ollama 使用显式 `reported_usage`；缺失为 null，保留合法实测零值，拒绝负数、布尔值和字符串计数 |
| 输入/输出都必须大于 0 才算已知 | 显式用量允许非负整数，包括零输出；每个方向独立记录，保留部分已知用量 |
| 截断响应用量丢失 | 先提取原生计数，再检查结束原因；失败事件与失败调用也计入已知总量，候选响应仍拒绝执行 |
| 网络失败无法取得用量 | 标为 unknown，预算保守预留，不能当作实测 0；不虚构已经丢失的服务端数据 |
| 脚本演示混入模型生成统计 | 新脚本响应使用普通 SPAN，标记 not_applicable，不发送模型和用量字段；真实 Ollama 使用 GENERATION |
| Token 和费用混淆 | 真实用量通过 `usage_details` 上传；本地调用显式记录零云 API 费用，标记 cost_scope=cloud_api_fee，本地运行成本未知 |

事件与报告区分 `known`、`partial`、`unknown`、`not_applicable`。`budget_accounted_tokens` 是预算控制记账，缺失实测时包含保守预留，不等于账单 Token。已知总量与完整总量分开，失败请求也参与累计。

共享预算层对旧 `LLMResponse` 保留原有兼容判断，避免将其默认的两个零重新解释成实测零；新 Ollama 响应通过显式字段消除歧义。没有更改历史实验文件、模型、评分或重新计算旧成绩。

## 实际运行与独立回读

- 使用原有自包含合成任务、本地 `qwen3.5:27b`，`think=false`，真实调用 1 次。
- 本次烟测最多 4 个动作、2 次编辑，Token 上限 60,000，输出上限 4,096，上下文 65,536。它是独立工程协议，不与历史 50 项实验作修复率比较。
- 目标与正常行为公开检查通过，状态 `ready_for_review`，`accepted=false`；没有独立评分器。
- 新增 `deploy/langfuse/verify_usage.py`：按 call_id 匹配原生计数、本地完成/失败事件及服务器 GENERATION，检查各方向总量、Trace 归属、费用范围和失败状态。不会发起模型调用。
- 另跑一次脚本任务，服务器回读得到 2 个 scripted-response SPAN、0 个 GENERATION，真实模型调用为 0。

在已配置 SDK 路径的 corecoder 终端，复核实际输出：

```powershell
python -B -m deploy.langfuse.verify_usage --run .tmp/langfuse-token-live-20261030 --env-file .tmp/langfuse-local/.env --output .tmp/token-usage-recheck-001.json --timeout 120
```

输出文件必须是新的项目 `.tmp` 文件；服务地址仅允许回环地址。完整配置见[本地 Langfuse](langfuse-local.md)。

## 验证与范围

- 全量回归 **1,861 passed、20 skipped，288.06s**，未启用模型测试或 Docker 专项开关。
- 最终定向 **29 passed，1.37s**，含全量完成后补充的服务器计数不一致负例；Ruff 通过。
- 截断、网络失败、零输出、部分缺失及非法计数由确定性测试覆盖；真实推理验证正常返回路径，未故意增加真实失败推理消耗。
- 初次受限权限下的定向测试中，既有子进程超时回收测试失败；在所需进程/IPC 权限下的完整回归中通过，未修改该项断言。
- 本轮仅新增 **1 次真实本地模型调用**和一次零推理脚本运行，未使用 DeepSeek 或其他付费 API；产物和缓存位于 D 盘。

[证据目录](langfuse_token_usage_20261030/)包含报告、事件、补丁、服务器回读与 JUnit，[文件哈希清单](langfuse-token-usage-20261030.json)支持离线核对，不包含密钥或登录信息。审批/排队的跨阶段追踪、补丁与测试耗时拆分仍属后续工作；当前修复的是用量统计与模型/脚本分类。
