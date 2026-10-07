# 求职交付证据索引

项目定位：基于 CoreCoder 的代码修复评测与可审批本地 Agent 服务。个人开源二次开发，用于展示受控实验、后端工程和失败分析；没有优于 Codex/Claude Code 的产品对照证据。

## 四条简历贡献如何核查

| 贡献 | 代码入口 | 验收或演示 |
| --- | --- | --- |
| 任务、预算、独立评分与 Trace | [执行器](../evals/runner.py)、[预算与事件](../evals/runtime.py) | [评测协议](p0-1-testing.md)；演示 report.json 和 patch.diff |
| 代码检索、上下文及编辑反馈实验 | [检索模块](../corecoder/retrieval/)、[事务保护](experiments/patch_transaction_v1.py)、[统一反馈](experiments/unified_feedback_worker_v1.py) | [第二仓库结果](second-repo-repair-v1.md)、[事务验证](patch-transaction-v1.md)、[已编辑函数对照](edited-context-v1.md) |
| API、持久化、幂等与审批恢复 | [API](../service/app.py)、[调度器](../service/manager.py)、[存储](../service/store.py)、[审批图](../workflows/approval.py) | [5 分钟演示](demo-guide.md)、[审批协议](workflow-approval-v1.md) |
| MCP 与部署可靠性 | [MCP Server](../mcp_servers/code_knowledge.py)、[互操作演示](../mcp_servers/demo.py)、[部署目录](../deploy/) | [MCP 报告](mcp-code-knowledge-v1.md)、[容器说明](container-deployment-v1.md)、[工程验收摘要](workflow-approval-acceptance-v1.json) |

基础 Agent 循环、模型客户端、压缩、原有工具与 MCP Client 来自 CoreCoder 上游。新 Server 不自动替换 API 默认检索，实验适配器不自动成为默认服务流程。目录入口用于核查实现，不能仅凭代码存在宣称已验证全部行为。

## 优先讲的结果

| 结果 | 对应结论与限制 |
| --- | --- |
| Click 三项、各三次：行块 3/9，函数 6/9 | 局部差异来自一个任务；只有三项不同缺陷；[冻结评分后复测](validation-repeat-v2.md) |
| ItsDangerous 三项、各一次：两组均 2/3 | 第二仓库未复现优势；[第二仓库](second-repo-repair-v1.md) |
| 六项、各一次：Qwen / DeepSeek 均 5/6 | 同流程换模型未解决 none-salt；[模型对照](provider-compare-v1.json) |
| 六项、各一次：原 / 源码契约上下文均 5/6 | 候选 none-salt 的 Controls 回归；少一次请求不是效率收益；[契约对照](source-contract-context-v1.json) |
| 事务离线拒绝 4/6 历史失败，9/9 正例通过 | 结构保护有作用但不能替代语义测试；[事务报告](patch-transaction-v1.md) |

各协议、任务池和重复次数分别报告，不合并为一个成功率。这些实验复用已查看任务，不能称作盲测、SWE-bench 成绩或稳定泛化提升。真实仓库历史共有 13 个不同任务；后续六项对照未增加缺陷数，也不意味着全部任务必须多文件修改。

## 验收数字从哪里来

| 范围 | 已记录结果 | 版本化来源 |
| --- | --- | --- |
| 最新 Windows 全量 | 1,096 passed、2 skipped | [语义验收事务摘要](semantic-patch-v1.json)；含上游与扩展测试 |
| 历史 Linux 专项 | 71 passed | [审批验收](workflow-approval-acceptance-v1.json) |
| 历史容器端到端 | 22 项检查通过 | 同上，container.checks |
| 历史真实 HTTP 审批故障 | 18 项检查通过 | 同上，host.http_checks |

历史文档交付核查没有重新运行模型、全量回归或部署验收；其核查记录见 [交付摘要](portfolio-delivery-v2.json)，明确区分历史验收与本次检查。

## 展示顺序与后续事项

1. 用 scripted fixture 展示提交、审批、重启恢复、独立验收、防重复执行；明确现场没有模型生成。
2. 运行只读 MCP 演示，展示 stdio、工具发现和带哈希读取；不宣称现场 API 已通过 MCP 修复。
3. 打开一个真实实验报告，解释独立评分、配对设置、失败补丁与成本；不在面试现场长时间重新推理。
4. 用 [简历与问答](resume-and-interview.md)说明个人贡献与未实现范围。

当前优先完成本人手动讲解、录屏与实际简历整理；仍未实现生产向量库、学习型 Reranker、多用户鉴权、逐任务沙箱、动态规划、多 Agent 或微调，不为补齐关键词继续扩张。

原始 `.tmp` 快照、日志和模型回答不随 Git 发布。工程 fixture 可离线演示，历史真实实验需要对应输入与隔离环境；发布或分享原始产物前另行选择归档范围。保留 [上游许可证](../LICENSE)与贡献归属。

已编辑函数保留对照：两个丢失方法的完整覆盖 0/2→2/2，但六项独立验收仍均 5/6；不能写为修复率提升。最新模型与 Windows 验收见 [报告](edited-context-v1.md)。

公开修复假设实验：引用与覆盖校验通过不等于语义正确，修正版局部对照原流程 1/2、假设流程 0/2；不采用为默认，不增加简历收益数字。见 [完整报告](repair-hypothesis-v1.md)。

公开语义提交门禁离线验收：3/3 个历史语义错误补丁不写回，历史及人工正确补丁 3/3 提交；0 次模型调用。此为候选提交可靠性证据，未接入默认服务，不增加修复率收益数字，见 [报告](semantic-patch-v1.md)。
