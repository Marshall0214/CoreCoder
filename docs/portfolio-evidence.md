# 求职交付证据索引

**当前核心进展（2026-10-08）：**同一次恢复同时提供锚点诊断和认证公开检查已完成新配对：三项已知任务中，同时通过冻结评分与公开边界检查从 1/3 提升到 2/3，空迭代器不再误输出 [[]]，假值异常保持通过；seekable 仍匹配失败。每组最多两次请求、原预算，默认流程暂不接入。下一步在冻结开发集扩大验证，不继续单例调参。 见 [联合恢复结果](anchor-public-recovery-v1.md)。

项目定位：基于 CoreCoder 的代码修复评测与可审批本地 Agent 服务。个人开源二次开发，用于展示受控实验、后端工程和失败分析；没有优于 Codex/Claude Code 的产品对照证据。

## 四条简历贡献如何核查

| 贡献 | 代码入口 | 验收或演示 |
| --- | --- | --- |
| 任务、预算、独立评分与 Trace | [执行器](../evals/runner.py)、[预算与事件](../evals/runtime.py) | [评测协议](p0-1-testing.md)；演示 report.json 和 patch.diff |
| 代码检索、上下文及编辑反馈实验 | [检索模块](../corecoder/retrieval/)、[事务保护](experiments/patch_transaction_v1.py)、[统一反馈](experiments/unified_feedback_worker_v1.py) | [第二仓库结果](second-repo-repair-v1.md)、[事务验证](patch-transaction-v1.md)、[已编辑函数对照](edited-context-v1.md) |
| API、持久化、幂等与审批恢复 | [API](../service/app.py)、[调度器](../service/manager.py)、[存储](../service/store.py)、[审批图](../workflows/approval.py) | [5 分钟演示](demo-guide.md)、[审批协议](workflow-approval-v1.md) |
| 可选暂存修复与公开验收发布 | [服务适配器](../service/tentative.py)、[暂存 Worker](experiments/tentative_feedback_worker_v1.py) | [服务报告](tentative-service-v1.md)、[模型发布对照](tentative-publication-v1.md) |
| MCP 与部署可靠性 | [MCP Server](../mcp_servers/code_knowledge.py)、[互操作演示](../mcp_servers/demo.py)、[部署目录](../deploy/) | [MCP 报告](mcp-code-knowledge-v1.md)、[容器说明](container-deployment-v1.md)、[工程验收摘要](workflow-approval-acceptance-v1.json) |

基础 Agent 循环、模型客户端、压缩、原有工具与 MCP Client 来自 CoreCoder 上游。新 Server 不自动替换 API 默认检索，实验适配器不自动成为默认服务流程。目录入口用于核查实现，不能仅凭代码存在宣称已验证全部行为。

## 优先讲的结果

| 结果 | 对应结论与限制 |
| --- | --- |
| 类范围检索新配对：开发 12/30→14/30 | 留出 9/20→11/20；有丢失成功和新控制回归，不替换默认，见 [配对报告](class-scoped-comparison-v1.md) |
| 50 项、5 仓库统一单次补丁基线：21/50 | 开发 12/30，留出 9/20；50 次新请求；记录缺陷类型与失败结果，见 [完整报告](expanded-baseline-v2.md) |
| Click 三项、各三次：行块 3/9，函数 6/9 | 局部差异来自一个任务；只有三项不同缺陷；[冻结评分后复测](validation-repeat-v2.md) |
| ItsDangerous 三项、各一次：两组均 2/3 | 第二仓库未复现优势；[第二仓库](second-repo-repair-v1.md) |
| 六项、各一次：Qwen / DeepSeek 均 5/6 | 同流程换模型未解决 none-salt；[模型对照](provider-compare-v1.json) |
| 六项、各一次：原 / 源码契约上下文均 5/6 | 候选 none-salt 的 Controls 回归；少一次请求不是效率收益；[契约对照](source-contract-context-v1.json) |
| 事务离线拒绝 4/6 历史失败，9/9 正例通过 | 结构保护有作用但不能替代语义测试；[事务报告](patch-transaction-v1.md) |

各协议、任务池和重复次数分别报告，不合并为一个成功率。这些实验复用已查看任务，不能称作盲测、SWE-bench 成绩或稳定泛化提升。历史原任务池有 13 个不同缺陷；本轮新增 17 个，当时固定任务集共 30 个；第二次再增 20 个，目前共 50 个、5 仓库。此前六项对照未增加缺陷数，也不意味着全部任务必须多文件修改。

## 验收数字从哪里来

| 范围 | 已记录结果 | 版本化来源 |
| --- | --- | --- |
| 最新 Windows 全量 | 1,206 passed、2 skipped | [检索配对摘要](class-scoped-comparison-v1.json)；含上游与扩展测试 |
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

任务级暂存反馈已接入可选 Worker：两轮只改暂存区，最终公开验收后发布；历史正确修复发布、错误修复保持任务起始字节，0 次新增推理。该结果为流程验收，不增加真实修复率，见 [报告](tentative-feedback-v1.md)。

真实模型发布对照完成：两项任务两种流程均修复 1/2；直接写入的失败分支留下错误源码，暂存发布拒绝该候选并保持起始字节，控制测试通过分支由 1/2 变为 2/2。正式对照 8 次本地 Qwen 请求、33,842 Token，新增验收发布阶段约 2.84 秒；没有修复率提升。全量 1,118 passed、2 skipped。下一步接入服务可选执行路径，见 [报告](tentative-publication-v1.md)。

可选暂存审批服务完成：两项认证真实缺陷可经 API 提交，审批后执行暂存修复与公开验收发布；拒绝、待审批取消和推理阶段取消不发布源码。16 项新测试覆盖成功/失败、重启、超时、幂等、外部变化、认证篡改及异常脱敏；两项真实快照经 ASGI/真实 Worker 到达待审批并拒绝，0 次模型请求。Windows 全量 1,134 passed、2 skipped；默认工作流不变。仍依赖历史本地产物，下一步生成独立认证任务包并验证批准后的真实 HTTP 推理，见 [报告](tentative-service-v1.md)。

补丁差异反馈完成：保持两次调用与原证据预算，历史差异可见且只使用当前片段编辑；两项新配对基线 1/2、候选 0/2。none-salt 恢复两处回退且 Controls 通过，但目标仍失败；Click 因 old 片段漏行被拒绝。8 次本地 Qwen 请求、33,798 Token；全量 1,144 passed、2 skipped。按停止条件冻结，不采用、不扩六项，不改服务；下一项核心工作先解决当前代码编辑锚点复述错误，见 [报告](patch-delta-v1.md)。


函数替换实验收尾：程序按已展示函数与文件 SHA256 提取旧文本，防止模型复述漏行；严格兼容单个 JSON 代码块后，两项反馈事务均可执行，但同答案回放最终基线 1/2、候选 0/2。八次本地 Qwen 请求共 34,137 Token；回放零新增推理。Windows 1,169 passed、2 skipped。保留可选原型，不采用、不扩任务、不改服务；下一步重点是修复逻辑的参数语义和行为保持。 见 [实验报告](function-replace-v1.md)。


源码重启反馈实验完成：失败观察保留，候选精确恢复到任务起始源码后重新生成补丁。两项全新配对原组 1/2、重启组 0/2，Controls 均 1/2；八次本地 Qwen 调用、35,012 Token，无预算或结构拒绝。回滚可执行，但语义错误仍再次生成。Windows 1,176 passed、2 skipped；不采用、不扩任务、不改服务。 见 [实验报告](restart-feedback-v1.md)。


公开执行参数轨迹完成：两组采集公开检查并校验普通执行结果一致；候选在原 6,000 字符证据预算内加入实际参数与到达行。none-salt 获得六个事件仍失败，Click 无空间加入有效轨迹且两组通过。两组均 1/2，none-salt 最终 AST 成对相同；八次 Qwen 请求 34,252 Token。Windows 1,181 passed、2 skipped。不采用、不扩此策略、不改服务；后续先检查任务覆盖与失败类型，避免继续围绕单例叠加反馈字段。 见 [实验报告](parameter-trace-v1.md)。


测试集扩充与完整评测完成：保留 13 项历史缺陷，新增 17 项上游真实缺陷，30 项全部准入、覆盖 5 仓库，模型调用前冻结 20 开发/10 留出。统一完整函数 BM25 + 单次补丁基线通过 12/30（40%），开发 8/20、留出 4/10；15 项行为失败、3 项无效补丁，全部保留。30 次本地 Qwen 调用、86,075 Token。参考函数诊断仅在评分后生成：18 项失败中 9 项未完整展示参考修改函数，9 项已展示仍失败，不作因果证明。Windows 1,187 passed、2 skipped。后续优先在开发集改善定位与补丁拒绝处理，不据留出具体答案调参。 见 [完整基线](expanded-baseline-v1.md)。


## 50 项分类评测更新（2026-10-07）

任务分类与第二次扩充完成：50 个上游真实缺陷、5 仓库、六类缺陷，开发 30/留出 20。全部重新入库验证并进行统一单次 Qwen 修复：21/50，开发 12/30、留出 9/20；50 次新请求、145,978 Token。结果分类：{"target_failed": 22, "passed": 21, "control_regression": 3, "invalid_patch": 3, "output_truncated": 1}。分类是可观察结果，不把失败直接归因于检索或推理。没有扩大工具、上下文或重试预算；旧 12/30 保留，不能把不同任务池的比例变化写成优化收益。Windows 1,198 passed、2 skipped；本轮未重跑容器或 HTTP。下一步仅在开发集验证核心策略，留出不逐题调参。 见 [50 项完整报告](expanded-baseline-v2.md)。


## 类范围检索优化更新（2026-10-08）

类范围检索优化已完成新配对：开发 12/30 → 14/30；留出 9/20 → 11/20；同一 50 项任务总体 21/50 → 25/50。新增成功 6 项、丢失成功 2 项；两组新调用合计 100 次。参考 Agentless/Aider 结构定位，改变限定名与类范围检索，模型、单次调用、上下文和评分预算一致。候选在 none-salt 出现新的正常行为回归；检索元数据也随策略变化，不能把全部收益归因于新增源码。决策：positive_development_and_heldout_pairing_optional_policy；默认 Agent/API 保持现状。Windows 1,206 passed、2 skipped。 见 [类范围检索配对](class-scoped-comparison-v1.md)。
