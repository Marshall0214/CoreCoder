# 交付清单与 JD 对照

更新：2026-10-07。勾选表示已有实现与证据；实验原型、上游能力和后续事项分别标明。

| 状态 | 交付项 | 证据与入口 |
| --- | --- | --- |
| 已完成 | 任务契约、独立工作区、评分、Trace、预算与失败报告 | [最小评测协议](p0-1-testing.md)、[预算处理](budget-aware-v1.md)、`evals/` |
| 已完成 | BM25 搜索工具、引用元数据及检索/上下文对照 | [search_code](p0-2-search-code.md)、[真实仓库结论](second-repo-repair-v1.md) |
| 实验原型 | Embedding、精确余弦、RRF Hybrid、结构/依赖证据 | [向量检索](vector-retrieval-v1.md)、[函数索引](function-index-audit-v1.md)；不是生产向量库 |
| 实验原型 | 行号补丁定位、换行边界修正和全新配对验证 | [补丁定位](anchored-patch-v1.md)；修复率未提高，保留默认方案 |
| 实验原型 | 公开符号解析、同名消歧、预算装填与三轮新对照 | [符号检索](symbol-directed-retrieval-v1.md)；点名函数覆盖改善，修复率无提升 |
| 实验原型 | 人工公开检查、离线认证、一次共享预算反馈与新回归 | [公开反馈](repair-public-feedback-v1.md)；两项已知失败 0/6→3/6，Token 2.57 倍，非通用测试生成 |
| 已完成 | FastAPI 提交/查询、SSE、幂等、取消、SQLite 持久化和进程清理 | [服务](service-mvp-v1.md)、[恢复](service-persistence-v2.md)、`service/` |
| 已完成 | LangGraph 固定计划、一次执行与独立验证分支 | [有限工作流](langgraph-workflow-v1.md)、`workflows/repair.py` |
| 已完成 | 人工审批、原生 SQLite 检查点、待审批恢复与防重放 | [审批](workflow-approval-v1.md)、`workflows/approval.py` |
| 已完成 | 只读代码知识 MCP Server 与两种 Client 互操作 | [MCP](mcp-code-knowledge-v1.md)、`mcp_servers/` |
| 已完成 | Docker/Linux 单服务部署、故障注入与清理 | [容器](container-deployment-v1.md)、[最新验收](workflow-approval-acceptance-v1.json) |
| 已完成 | 总览、演示、简历与面试入口 | [总览](project-overview.md)、[演示](demo-guide.md)、[简历](resume-and-interview.md) |

## JD 可以如何对应

| JD 能力 | 可证明的工作 | 范围 |
| --- | --- | --- |
| Python、异步与后端工程 | API、Pydantic、任务队列、子进程、取消、SSE | 个人扩展；本地服务 |
| Agent Workflow / Framework | LangGraph 节点、条件分支、interrupt/Command、检查点 | 固定计划；一次修复尝试 |
| Prompt / Context / Structured Output | 片段补丁协议、证据装填/去重/预算、Pydantic 工具及计划 | 多种实验模式分别固定协议 |
| RAG | 代码语料、分块、BM25、Embedding、Dense/RRF 与指标 | 小语料实验；向量数据库和 Reranking 待实现 |
| MCP / Tool Calling | 三个只读工具、stdio、结构化结果、哈希与路径约束 | 自建 Server；基础 Client 来自上游 |
| Evaluation / Optimization | 独立评分、对照、重复、Trace、成本与失败归因 | 小样本探索；无普遍提升结论 |
| Reliability / Deployment | 幂等、审批恢复、孤儿清理、Docker/Linux、真实强制退出验收 | 单 owner SQLite；无分布式/生产负载证明 |
| LLM 原理、训练与研究 | 可结合模型接口/用量解释基础概念 | 项目没有训练 Transformer、微调或论文成果 |

Memory、Reflection、Multi-Agent 等名称不能只因上游存在工具就算个人完成。当前没有个人验证的协作式多 Agent 系统；文件撤销 checkpoint 与本轮 LangGraph 工作流 checkpoint 是不同机制。

## 明确未完成

- [ ] 任意仓库接入服务、约 20 项真实案例、完整跨文件基准及全部组合消融。
- [ ] LLM 动态规划、通用反馈反思、逐工具审批和执行中断点续修。
- [ ] PostgreSQL/Redis、向量数据库、学习型 Reranker。
- [ ] 多用户鉴权、审批身份和权限审计、每任务容器沙箱。
- [ ] 生产并发负载、云上线、远程 MCP、多 Agent 与微调。

本阶段以“可信任务上的独立验证 + 有证据的机制实验 + 可演示本地服务”交付，不继续为了补关键词无限扩展。岗位明确要求哪项，再选一项单独立协议和验收。

## 交付复查

- [x] 保留上游 LICENSE 与作者归属，README 标明扩展入口。
- [x] 实验结果分任务池报告，评分修正、失败和不确定性保留。
- [x] 简历表述只写已实现能力；演示将 scripted 与真实模型实验分开。
- [x] 工程验收数字来自版本化 JSON；两个 Windows 跳过项不算通过。
- [x] 使用私有演示端口/目录，项目产物写 D 盘，不停止已有用户服务。
- [ ] 如需共享原始实验产物，另行归档 `.tmp/` 指定目录并核查敏感信息；当前 Git 不包含全量历史原始输出。
- [ ] 用户实际演讲/录屏、公开发布或提交简历。本轮交付文档不表示已发布。

本轮文档交付检查与演示复跑结果见 [演示指南](demo-guide.md)末尾：README 约束 1 passed、54 个本地链接有效、9 段 PowerShell 语法通过、HTTP 18 项检查通过、MCP stdio 演示成功。运行时和冻结实验未修改，无需重跑模型或重建镜像。

最新 Windows 回归为 919 passed、2 skipped，见 [公开反馈摘要](repair-public-feedback-v1.json)。公开反馈为独立实验模式，不改变固定计划服务的一次修复协议。
