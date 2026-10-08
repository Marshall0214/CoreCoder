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
| 实验原型 | 点名类构造函数与参数转发片段装填、三轮反馈对照 | [转发上下文](repair-forwarding-feedback-v1.md)；两组均 3/6，新策略有盐值隔离回归，不替换默认 |
| 实验原型 | 人工盐值关系矩阵、检查 v2 与离线变异验证 | [盐值关系](salt-relations-audit-v1.md)；正例 11/11、6 变异和 6 历史失败均拒绝，无模型调用 |
| 实验原型 | 相同检查/上下文下的公开关系矩阵三轮反馈对照 | [矩阵反馈](salt-relations-feedback-v1.md)；两组均 0/3，冻结分支，未提升默认方案 |
| 实验原型 | 人工小任务 thinking 开关校准与分阶段验证 | [校准](thinking-calibration-v1.md)；两组 4/4，on Token 2.54 倍，非真实仓库收益 |
| 实验原型 | 唯一匹配编辑事务与最多一次统一失败反馈 | [事务保护](patch-transaction-v1.md)、[统一反馈](unified-feedback-v1.md)；结构校验不能替代语义验收 |
| 实验原型 | Qwen / DeepSeek 同流程配对对照 | [模型对照](provider-compare-v1.md)；两组均 5/6，无成功率收益 |
| 实验原型 | 带来源的源码契约事实及同预算上下文对照 | [契约上下文](source-contract-context-v1.md)；两组均 5/6，候选有 Controls 回归 |
| 实验原型 | 区分候选异常与检查故障、一次运行时反馈 | [运行时反馈](runtime-feedback-v1.md)；异常记录 8→0，独立验收仍 5/6，Token 增加 |
| 已完成 | FastAPI 提交/查询、SSE、幂等、取消、SQLite 持久化和进程清理 | [服务](service-mvp-v1.md)、[恢复](service-persistence-v2.md)、`service/` |
| 已完成 | LangGraph 固定计划、一次执行与独立验证分支 | [有限工作流](langgraph-workflow-v1.md)、`workflows/repair.py` |
| 已完成 | 人工审批、原生 SQLite 检查点、待审批恢复与防重放 | [审批](workflow-approval-v1.md)、`workflows/approval.py` |
| 已完成 | 只读代码知识 MCP Server 与两种 Client 互操作 | [MCP](mcp-code-knowledge-v1.md)、`mcp_servers/` |
| 已完成 | Docker/Linux 单服务部署、故障注入与清理 | [容器](container-deployment-v1.md)、[最新验收](workflow-approval-acceptance-v1.json) |
| 已完成 | 总览、演示、简历与面试入口 | [总览](project-overview.md)、[演示](demo-guide.md)、[简历](resume-and-interview.md) |
| 已完成 | 求职贡献与代码/结果逐项核对 | [证据索引](portfolio-evidence.md)、[当前交付核查](portfolio-delivery-v2.json)；不表示用户已录屏或发布 |

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

转发上下文实验后 Windows 全量 924 passed、2 skipped；两组均 3/6，收益未提高，源码语法启发式不能代替参数语义验证。

盐值关系离线验证后，最新 Windows 全量 934 passed、2 skipped，见 [离线摘要](salt-relations-audit-v1.json)。检查 v2 尚未接入模型反馈或默认服务。

关系矩阵反馈对照后最新 Windows 全量为 942 passed、2 skipped；收益为零，保留失败与成本证据。

最新 Windows 回归 952 passed、2 skipped；配置校准未改变默认模型和冻结评分。

编辑事务离线验证完成：历史失败补丁拦截 4/6，其余 2 个事务通过但语义仍失败；正确示例 9/9，模型调用 0。修正取消测试的进程退出竞态后，最终 Windows 全量 **971 passed、2 skipped**，见 [事务摘要](patch-transaction-v1.json)。适配器未接入默认服务，仍需独立语义验收。

事务反馈闭环验收完成：正常模式两调用上限和共享预算有回归验证；6 次真实模型调用验证三个合成故障恢复，两种反馈均 3/3，详细诊断成本增加约 39.1%。最终 Windows **983 passed、2 skipped**，见 [反馈摘要](transaction-feedback-v1.json)。不计真实缺陷成功率，默认服务不变。

真实任务统一失败反馈验收完成：六项任务两组均 5/6，各 25,837 Token；16 次全新调用，无额外成功数。none-salt 第二轮重复定义被拦截，第一轮候选保持不变。最终 Windows **999 passed、2 skipped**，见 [统一反馈摘要](unified-feedback-v1.json)。默认服务不变，未触发的真实第一轮事务反馈不宣称获得模型收益。

Qwen / DeepSeek 固定统一反馈流程对照已完成：六项已查看缺陷各一次，两组均 5/6、各 8 次请求；Token 25,413 / 23,981。none-salt 仍分别存在签名兼容错误和不存在成员引用，未因更换模型解决。最终 Windows 1,013 passed、2 skipped；冻结结果、不替换默认服务，见 [模型对照报告](provider-compare-v1.md)。

源码契约上下文对照完成：零调用审查后，只用 Qwen 对六项已查看任务各比较一次；原上下文与候选均 5/6。候选 none-salt 删除盐值回退，Target/Controls 都失败；公开检查混合执行错误导致停止反馈，因此 Token 减少不是效率收益。共 15 次本地调用、0 次 DeepSeek 调用，全量 1,023 passed、2 skipped。冻结原型，建议收敛交付，见 [契约上下文报告](source-contract-context-v1.md)。

运行时异常反馈完成：结构化 traceback 区分候选异常与检查故障，沿用一次修正与共享预算。六项两组均 5/6，none-salt 公开运行异常从 8 个降至 0 个但仍有语义和 Controls 失败；Token 20,393 / 27,206。全量 1,044 passed、2 skipped，保留可选，不替换默认；下一步验证已编辑函数的原文保留，见 [运行时反馈](runtime-feedback-v1.md)。

已编辑函数保留对照完成：成功提交的修改函数在反馈中优先提供当前完整原文，保持 6,000 字符与五函数上限；覆盖 0/2→2/2，但两组独立验收仍 5/6，Token 27,206 / 27,493。16 次本地 Qwen 请求、0 次 DeepSeek 请求。全量 1,056 passed、2 skipped；保留可选，不替换默认。下一步先核查参数语义与修复假设，见 [报告](edited-context-v1.md)。

公开修复假设实验完成：写回前校验真实公开测试、当前函数引用与失败覆盖，执行后标记假设结果。初版校验过度拒绝已修正并单独复测；v1 六项原/假设 5/6、4/6，v2 两项 1/2、0/2，不采用为默认。共 24 次本地 Qwen 请求、0 次 DeepSeek 请求，全量 1,081 passed、2 skipped。下一步先离线验证最终候选的公开语义检查与提交/回滚关系，见 [报告](repair-hypothesis-v1.md)。

最终候选公开语义验收事务离线完成：副本通过结构与公开行为检查后才写回，失败保留诊断且不写原文；写入异常记录恢复结果。3/3 历史语义错误拒绝，3/3 历史/人工正确补丁提交，0 次模型与私有评分请求。全量 1,096 passed、2 skipped。尚未接入 Worker 或默认服务；下一步验证第一轮暂存、一次反馈及任务级失败恢复的生命周期，见 [报告](semantic-patch-v1.md)。

任务级暂存反馈生命周期完成：第一轮与一次反馈只改暂存区，最终公开语义检查后发布净修改；失败保持任务起始版本，外部变化不覆盖。两项历史完整回答重放：正确修复发布、错误修复不发布，四次请求除 unittest 耗时行外一致；0 次新增模型与私有评分请求。全量 1,112 passed、2 skipped。接入可选 Worker，未接入默认 API；下一步固定模型与预算做两项全新发布对照，见 [报告](tentative-feedback-v1.md)。

真实模型发布对照完成：两项任务两种流程均修复 1/2；直接写入的失败分支留下错误源码，暂存发布拒绝该候选并保持起始字节，控制测试通过分支由 1/2 变为 2/2。正式对照 8 次本地 Qwen 请求、33,842 Token，新增验收发布阶段约 2.84 秒；没有修复率提升。全量 1,118 passed、2 skipped。下一步接入服务可选执行路径，见 [报告](tentative-publication-v1.md)。

可选暂存审批服务完成：两项认证真实缺陷可经 API 提交，审批后执行暂存修复与公开验收发布；拒绝、待审批取消和推理阶段取消不发布源码。16 项新测试覆盖成功/失败、重启、超时、幂等、外部变化、认证篡改及异常脱敏；两项真实快照经 ASGI/真实 Worker 到达待审批并拒绝，0 次模型请求。Windows 全量 1,134 passed、2 skipped；默认工作流不变。仍依赖历史本地产物，下一步生成独立认证任务包并验证批准后的真实 HTTP 推理，见 [报告](tentative-service-v1.md)。

2026-10-07 优先级收敛：暂存审批服务 v1 阶段收尾，独立任务包和更多部署暂缓。当前主线改为核心修复：在固定预算内验证补丁前后差异反馈能否纠正第一轮错误修改，见 [核心方案](core-repair-next.md)。此前 Windows 1,134 passed、2 skipped 为既有验收，本次仅修改计划与文档，没有新增模型实验或运行测试。

补丁差异反馈完成：保持两次调用与原证据预算，历史差异可见且只使用当前片段编辑；两项新配对基线 1/2、候选 0/2。none-salt 恢复两处回退且 Controls 通过，但目标仍失败；Click 因 old 片段漏行被拒绝。8 次本地 Qwen 请求、33,798 Token；全量 1,144 passed、2 skipped。按停止条件冻结，不采用、不扩六项，不改服务；下一项核心工作先解决当前代码编辑锚点复述错误，见 [报告](patch-delta-v1.md)。


函数替换实验收尾：程序按已展示函数与文件 SHA256 提取旧文本，防止模型复述漏行；严格兼容单个 JSON 代码块后，两项反馈事务均可执行，但同答案回放最终基线 1/2、候选 0/2。八次本地 Qwen 请求共 34,137 Token；回放零新增推理。Windows 1,169 passed、2 skipped。保留可选原型，不采用、不扩任务、不改服务；下一步重点是修复逻辑的参数语义和行为保持。 见 [实验报告](function-replace-v1.md)。


源码重启反馈实验完成：失败观察保留，候选精确恢复到任务起始源码后重新生成补丁。两项全新配对原组 1/2、重启组 0/2，Controls 均 1/2；八次本地 Qwen 调用、35,012 Token，无预算或结构拒绝。回滚可执行，但语义错误仍再次生成。Windows 1,176 passed、2 skipped；不采用、不扩任务、不改服务。 见 [实验报告](restart-feedback-v1.md)。


公开执行参数轨迹完成：两组采集公开检查并校验普通执行结果一致；候选在原 6,000 字符证据预算内加入实际参数与到达行。none-salt 获得六个事件仍失败，Click 无空间加入有效轨迹且两组通过。两组均 1/2，none-salt 最终 AST 成对相同；八次 Qwen 请求 34,252 Token。Windows 1,181 passed、2 skipped。不采用、不扩此策略、不改服务；后续先检查任务覆盖与失败类型，避免继续围绕单例叠加反馈字段。 见 [实验报告](parameter-trace-v1.md)。


测试集扩充与完整评测完成：保留 13 项历史缺陷，新增 17 项上游真实缺陷，30 项全部准入、覆盖 5 仓库，模型调用前冻结 20 开发/10 留出。统一完整函数 BM25 + 单次补丁基线通过 12/30（40%），开发 8/20、留出 4/10；15 项行为失败、3 项无效补丁，全部保留。30 次本地 Qwen 调用、86,075 Token。参考函数诊断仅在评分后生成：18 项失败中 9 项未完整展示参考修改函数，9 项已展示仍失败，不作因果证明。Windows 1,187 passed、2 skipped。后续优先在开发集改善定位与补丁拒绝处理，不据留出具体答案调参。 见 [完整基线](expanded-baseline-v1.md)。


## 50 项分类评测更新（2026-10-07）

任务分类与第二次扩充完成：50 个上游真实缺陷、5 仓库、六类缺陷，开发 30/留出 20。全部重新入库验证并进行统一单次 Qwen 修复：21/50，开发 12/30、留出 9/20；50 次新请求、145,978 Token。结果分类：{"target_failed": 22, "passed": 21, "control_regression": 3, "invalid_patch": 3, "output_truncated": 1}。分类是可观察结果，不把失败直接归因于检索或推理。没有扩大工具、上下文或重试预算；旧 12/30 保留，不能把不同任务池的比例变化写成优化收益。Windows 1,198 passed、2 skipped；本轮未重跑容器或 HTTP。下一步仅在开发集验证核心策略，留出不逐题调参。 见 [50 项完整报告](expanded-baseline-v2.md)。


## 类范围检索优化更新（2026-10-08）

类范围检索优化已完成新配对：开发 12/30 → 14/30；留出 9/20 → 11/20；同一 50 项任务总体 21/50 → 25/50。新增成功 6 项、丢失成功 2 项；两组新调用合计 100 次。参考 Agentless/Aider 结构定位，改变限定名与类范围检索，模型、单次调用、上下文和评分预算一致。候选在 none-salt 出现新的正常行为回归；检索元数据也随策略变化，不能把全部收益归因于新增源码。决策：positive_development_and_heldout_pairing_optional_policy；默认 Agent/API 保持现状。Windows 1,206 passed、2 skipped。 见 [类范围检索配对](class-scoped-comparison-v1.md)。
