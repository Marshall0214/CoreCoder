# CoreCoder 扩展项目总览

**最新小试验：**公开 predicate 参数证据已实现并完成共享首轮候选/日志的严格对照。
整项 0/1 → 0/1；第二轮补丁完整且 locate 尾部公开断言推进，replace 仍失败，不接入默认。
全量 1331 passed、4 skipped；见 [实验报告](predicate-runtime-v1.md)。

**当前核心进展（2026-10-08）：**已完整新跑同一批 50 项、三组共 150 次任务执行。仅检索 → 双重验证反馈流程 **25/50 → 32/50（50% → 64%，+14 个百分点）**，新增 7 项、丢失 0 项；首轮请求和回答全部相同。调用 50 → 71，Token 143,193 → 216,492（+51.2%）；失败回滚后正常行为检查 48/50 → 50/50。原始七工具组 50 项均预算停止，2 个最终补丁有效、0 项正常完成，不将其解释为通用成功率。任务已知、单轮探索性对照，默认 Agent/API 未变。见 [完整对照](system-comparison-v1.md)和[逐项数据](system-comparison-v1.json)。

**失败重定位试验已收尾：**8 项已知开发任务，原反馈与新策略均 2/8，无新增或丢失成功；Token 仅下降约 1.4%，不采用、不扩大运行。现有 32/50 结果保持不变。见 [失败重定位报告](failure-context-v1.md)。

**诊断反馈修正已验证：**分组展示失败和通过约束、首轮修改摘要、最小唯一补丁提示。
predicate 第二轮输出由 2048 Token 截断变为 229 Token 可应用补丁，但目标语义仍失败；
8 项配对整体 2/8 → 1/8，丢失 none-salt 成功，因此不采用、不扩大运行。
全量 1323 passed、4 skipped；默认流程和 32/50 完整成绩不变。见 [报告](diagnostic-feedback-v1.md)。

更新：2026-10-08。定位：基于 CoreCoder 的代码修复实验与本地服务，作为 AI Agent / LLM Application Engineer 求职项目。

## 核心需求与完成状态

输入可信任务的缺陷描述和指定源码版本，生成候选补丁，由独立验证器判断结果，同时记录证据来源、Token、耗时与失败原因。围绕同一执行器比较检索和上下文策略，再通过 API、MCP 和持久化审批提供可演示的工程入口。

核心研究问题：在固定 LLM、工具集合、任务预算和评测协议下，不同代码检索与上下文组织策略如何影响修复结果和执行成本？工程问题：任务如何提交、审批、取消、恢复，并防止重复执行？

**当前阶段可以交付。**评测、实验报告、本地服务、MCP、审批检查点和容器验收均有记录。服务接收 catalog 中的可信人工任务，并增加两项认证真实缺陷的可选暂存审批入口；其他真实仓库实验仍通过独立脚本运行，未支持任意 GitHub 仓库。完整跨文件基准和全部 JD 要求未完成。

开发必要性来自对内部机制的实现、替换和验证需求：能够固定输入与预算，改一种证据策略，再用相同独立评分解释差异。这是求职工程作品与探索性实验，没有真实用户需求验证或优于成熟 Coding Agent 的证据。

## 阅读入口

| 要看什么 | 入口 |
| --- | --- |
| 50 项完整三组对照与成本 | [system-comparison-v1.md](system-comparison-v1.md) |
| 5 分钟离线工程演示 | [demo-guide.md](demo-guide.md) |
| 简历与面试说明 | [resume-and-interview.md](resume-and-interview.md) |
| 求职贡献、代码与验收的对应证据 | [portfolio-evidence.md](portfolio-evidence.md) |
| 实现/证据/未完成清单 | [delivery-checklist.md](delivery-checklist.md) |
| 最新工程验收摘要 | [workflow-approval-acceptance-v1.json](workflow-approval-acceptance-v1.json) |
| 最新检索优化配对 | [class-scoped-comparison-v1.md](class-scoped-comparison-v1.md) |
| 50 项、5 仓库分类基线 | [expanded-baseline-v2.md](expanded-baseline-v2.md) |
| 50 项固定任务与提交清单 | [expanded-suite-v2.json](expanded-suite-v2.json) |
| 历史第二仓库实验结论 | [second-repo-repair-v1.md](second-repo-repair-v1.md) |
| 最新补丁定位优化与失败归因 | [anchored-patch-v1.md](anchored-patch-v1.md) |
| 符号定向检索与三轮修复对照 | [symbol-directed-retrieval-v1.md](symbol-directed-retrieval-v1.md) |
| 公开检查与一次反馈修复 | [repair-public-feedback-v1.md](repair-public-feedback-v1.md) |
| 参数转发上下文与反馈对照 | [repair-forwarding-feedback-v1.md](repair-forwarding-feedback-v1.md) |
| 盐值关系矩阵与离线变异验证 | [salt-relations-audit-v1.md](salt-relations-audit-v1.md) |
| 关系矩阵真实反馈对照 | [salt-relations-feedback-v1.md](salt-relations-feedback-v1.md) |
| Thinking 开关人工小任务校准 | [thinking-calibration-v1.md](thinking-calibration-v1.md) |
| Qwen / DeepSeek 固定流程对照 | [provider-compare-v1.md](provider-compare-v1.md) |
| Qwen 源码契约上下文与回归 | [source-contract-context-v1.md](source-contract-context-v1.md) |
| 暂存发布真实模型对照 | [tentative-publication-v1.md](tentative-publication-v1.md) |
| 暂存发布的可选服务审批入口 | [tentative-service-v1.md](tentative-service-v1.md) |
| 补丁差异反馈结果（未采用） | [patch-delta-v1.md](patch-delta-v1.md) |
| 函数替换协议（可选原型，未采用） | [function-replace-v1.md](function-replace-v1.md) |
| 从起始源码重新修复（未采用） | [restart-feedback-v1.md](restart-feedback-v1.md) |
| 公开执行参数轨迹（未采用） | [parameter-trace-v1.md](parameter-trace-v1.md) |
| 当前核心优化与停止条件 | [core-repair-next.md](core-repair-next.md) |
| 任务级暂存反馈与语义发布（可选 Worker） | [tentative-feedback-v1.md](tentative-feedback-v1.md) |
| 最终候选公开语义验收事务（离线） | [semantic-patch-v1.md](semantic-patch-v1.md) |
| 公开修复假设校验与结果追踪（未采用） | [repair-hypothesis-v1.md](repair-hypothesis-v1.md) |
| 已编辑函数当前版本保留与对照 | [edited-context-v1.md](edited-context-v1.md) |
| 候选运行时异常观察与有界反馈 | [runtime-feedback-v1.md](runtime-feedback-v1.md) |
| 已有方法与下一步依据 | [repair-methods-research-v1.md](repair-methods-research-v1.md) |

## 架构和个人贡献边界

```mermaid
flowchart TD
    API[FastAPI / 幂等键 / 生命周期 SSE] --> Store[SQLite 任务与审批决定]
    API --> Graph[LangGraph 固定计划 / 审批 interrupt]
    Graph --> CP[每任务 SQLite 原生检查点]
    Graph --> Worker[独立 Worker / 任务工作区]
    Worker --> Run[既有评测执行器 / 候选补丁]
    Run --> Verify[干净副本独立验证]
    Verify --> Artifacts[补丁 / 报告 / Trace / 用量]
    API --> Approval[可选认证任务 / 持久化审批]
    Approval --> Tentative[独立暂存修复 / 一次反馈]
    Tentative --> PublicGate[认证公开检查]
    PublicGate --> Publish[发布到任务源码副本 / 失败保留原文]
    Publish --> Artifacts
    Experiments[检索与上下文实验适配器] --> Run
    MCP[只读代码知识 MCP Server] --> Evidence[BM25 / 带路径行号及哈希的证据]
    Experiments --> Evidence
```

MCP 是独立工具接入与互操作成果，没有自动替换服务默认检索。实验中的单次补丁协议与多轮工具 Agent 协议分别报告，不混用结果。

| 来源 | 实际内容 |
| --- | --- |
| CoreCoder 上游 | 基础 Agent 循环、模型客户端、压缩、工具、权限、会话、子 Agent、MCP Client、文件撤销；保留 [MIT 许可证](../LICENSE)及作者归属 |
| 本项目评测扩展 | `evals/`：任务契约、预算、独立工作区与评分、补丁与 JSONL Trace、失败分类；`tests/` 对应回归 |
| 本项目检索扩展 | `corecoder/retrieval/`、可选 search_code；`docs/experiments/` 中 Dense/RRF、结构/依赖证据及受控实验适配器 |
| 本项目工程扩展 | `service/`、`workflows/`、`mcp_servers/`、`deploy/`：API、SQLite、审批恢复、进程清理、只读工具服务与容器验收 |

个人贡献应表述为“基于开源二次开发，设计并实现上述扩展”，不能将基础引擎或上游已有能力写成从零原创。代码行数只统计原 corecoder 包，与包外扩展规模分别看待。

## 实验结果：收益与失败都保留

下表来自独立报告，不相加形成统一成功率；重复次数不增加不同缺陷数。除明确标出的 DeepSeek 对照，模型使用本地 Ollama qwen3.5:27b，具体模式、预算和评分以各报告为准。

| 任务池 / 对照 | 实测 | 能说明什么 |
| --- | --- | --- |
| 11 项合成开发任务，BM25 / Dense 离线检索 | Recall@5：57.58% / 80.30% | 标签是参考补丁涉及文件，属于检索诊断，见 [向量检索](vector-retrieval-v1.md) |
| 同批 11 项，三轮新补丁对照 | BM25 14/33；Dense 12/33 | 召回改善没有转化成稳定修复收益，见 [配对复测](vector-repair-repeat-v1.md) |
| Click 7 项开发任务，各三次 | 行块 0/21；完整函数 3/21 | 差异来自 invoke-missing 一项，见 [开发重复对照](function-index-repair-repeat-v1.md) |
| Click 3 项、评分 v2、各三次新调用 | 行块 3/9；完整函数 6/9 | 差异来自颜色校验；任务已被查看，非新的盲测，见 [评分后复测](validation-repeat-v2.md) |
| ItsDangerous 3 项、各一次 | 两策略均 2/3 | 第二仓库未复现成功率优势，见 [第二仓库对照](second-repo-repair-v1.md) |
| 同一批 Click/ItsDangerous 6 项，补丁定位新对照 | 边界修正后原文匹配 3/6；行号定位 3/6 | 无效补丁减少，Token 增加，未替换默认；见 [补丁定位](anchored-patch-v1.md) |
| 同一批 6 项，完整函数 BM25 / 符号优先，各三次新调用 | 点名函数覆盖 5/7 / 7/7；修复均 12/18 | 覆盖改善未转化为修复收益，保留默认；见 [符号检索](symbol-directed-retrieval-v1.md) |
| 已知失败两项，各三次；单次 / 一次公开反馈 | 0/6 / 3/6；Token 16,056 / 41,316 | usage-empty 恢复、none-salt 仍失败；另四项单次新回归 4/4，不混合成功率；见 [公开反馈](repair-public-feedback-v1.md) |
| 同两项任务，各三次；原反馈 / 转发上下文反馈 | 两组均 3/6，none-salt 均 0/3 | 新策略发生盐值隔离回归，不替换默认；见 [转发上下文](repair-forwarding-feedback-v1.md) |
| none-salt 一项，各三次；检查 v2 / 加关系矩阵 | 两组均 0/3 | 关系表达未带来修复收益，冻结实验；见 [矩阵反馈](salt-relations-feedback-v1.md) |
| 六项，各一次；公开反馈 / 统一反馈 | 两组均 5/6 | 事务保护拒绝重复定义，语义失败未解决；见 [统一反馈](unified-feedback-v1.md) |
| 六项，各一次；同流程 Qwen / DeepSeek | 两组均 5/6 | 换模型未解决 none-salt；见 [模型对照](provider-compare-v1.md) |
| 六项，各一次；原 / 源码契约上下文 | 两组均 5/6 | 候选 Controls 回归；少一次调用不是提效；见 [契约上下文](source-contract-context-v1.md) |

Click 7 项、Click 3 项、ItsDangerous 3 项三个历史任务池合计 13 个不同任务，不代表 13 项都必须多文件修改。本轮新增 17 项，当时固定任务集为 30 项、5 仓库；最新扩充为 50 项，见 [完整基线](expanded-baseline-v1.md)。后续检索、补丁与公开反馈实验复用了其中六项，没有增加不同缺陷数。passed 是满足独立 Target/Controls 和修改约束，不代表完整上游测试或生产正确性。评分错误修正记录与新调用分开，不覆盖旧结果。

原始实验输入、模型回答和日志位于被 Git 忽略的 `.tmp/`，复跑真实实验需要报告指定的准入快照、隔离环境及模型身份；仅 clone 不能直接重建所有历史结果。工程演示使用仓库内人工 fixture，可不依赖这些实验产物或模型 API。

## 工程验收与边界

历史审批工程验收：Windows **864 passed、2 skipped**；Linux **71 passed、无跳过**；**22 项容器端到端检查、18 项真实 HTTP 审批故障检查通过**。出处为 [验收摘要](workflow-approval-acceptance-v1.json)。最新检索优化后 Windows 全量 **1,206 passed、2 skipped**，见 [配对报告](class-scoped-comparison-v1.md)；本轮未重跑 Linux/容器/HTTP 验收。这些是软件回归/故障验收数字，不能当作真实修复成功率。

待审批任务保存原生 interrupt，Worker 退出并释放并发名额；批准用 Command 恢复，拒绝不执行。相同决定重复提交不重跑；待审批重启保留，执行中崩溃清理进程并标记 interrupted，不自动重放副作用。详见 [审批协议](workflow-approval-v1.md)。

检索向量索引为内存精确余弦，未实现生产向量数据库/ANN 或学习型 Reranker。计划是代码生成的固定契约，未实现 LLM 动态规划。服务为本地单 owner SQLite，未实现 PostgreSQL/Redis、多用户鉴权、逐工具审批、每任务容器沙箱或生产负载验证。整个服务容器的限制不能替代逐任务隔离。

新增工程产物、临时文件及本机 Docker 数据放在 D 盘；Docker Desktop 自身仍可能写系统配置和日志。历史模型实验已冻结；随后补丁定位对照 24 次、正式符号检索对照 36 次新调用分别报告，没有覆盖旧结果或替换默认方案。符号检索暂停原型另存未完成记录，不并入正式结果。

公开反馈本轮新增 22 次模型调用（18 次配对实验、4 次单次回归）。只为两项任务提供人工公开检查和一次预算内反馈，未实现通用测试生成或接入服务默认流程。

参数转发上下文本轮另新增 24 次模型调用，两种反馈均 3/6；none-salt 未修复，新的错误盐值隔离行为被公开检查及独立 Controls 拦截。

盐值关系检查 v2 离线验证：人工正例 11/11、六个变异与六个历史失败补丁全部拒绝，0 次模型调用。它验证检查的已知区分能力，尚无模型收益结果，见 [关系验证](salt-relations-audit-v1.md)。

关系矩阵反馈本轮 12 次全新模型调用，两组均 0/3，无收益；重复方法定义和错误默认值保留诊断，不改历史评分或默认策略。

四个人工小任务另做 thinking 开关校准，共 8 次新调用，两组均 4/4；on Token 为 off 的 2.54 倍，无准确率收益。该结果不计入真实仓库成功率，不能替代 ItsDangerous 缺陷验收。编辑事务保护的离线验证已完成，见 [事务报告](patch-transaction-v1.md)。

可选编辑事务保护：临时副本唯一匹配、Python 编译、新增重复定义检查及隔离模块加载，通过后才写回；写入异常尝试回滚。6 个历史失败补丁拦截 4 个，剩余 2 个仍被公开语义检查拒绝；9 个正确示例全部通过，0 次模型调用。未接入默认服务，不宣称提升真实修复率或跨进程原子性。另修正四处取消测试的进程退出竞态，服务运行时不变。

事务拒绝原因反馈已完成：最多两次补丁尝试、正常模式最多两次模型请求，共享 Token 预算。三个合成故障注入任务做一次真实恢复反馈，两组均 3/3，6 次新调用；详细诊断 Token 增加约 39.1%，未见准确率收益。该结果不计真实缺陷成功率，不设为默认策略，见 [事务反馈](transaction-feedback-v1.md)。

真实任务统一反馈完成：事务拒绝使用原版本、公开断言失败使用当前候选，最多两次调用且共享预算。六项已查看的真实缺陷两组均 5/6、各 25,837 Token，共 16 次新调用。统一模式拦截 none-salt 第二轮重复定义但仍未修复语义；无成功率收益，保留可选，见 [统一反馈](unified-feedback-v1.md)。

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
