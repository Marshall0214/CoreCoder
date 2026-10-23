# 43/50 → 47/50：修复实验的证据与面试说明

这份材料回答五个问题：对照是谁、改了什么、怎样算成功、哪里仍失败、花了多少 Token。
**结论限定为已知 50 项任务池的一次历史完整对照：通过 43 → 47，新增成功 5、丢失成功 1，Token 降低 9.38%。**
本次只整理和离线核算历史记录，没有调用模型、重新评分或改写原实验结果。

## 1. 先看证据入口

| 材料 | 用途 |
| --- | --- |
| [原始基线](repair50_evidence/inputs/baseline.json)、[优化轮](repair50_evidence/inputs/candidate.json) | 两份完整 50 项报告，含配置、调用用量、工作流状态和原始评分计数 |
| [任务清单](repair50_evidence/inputs/manifest.json) | 来源、固定源码、允许修改文件、准入结果和目录哈希 |
| [汇总 JSON](repair50_evidence/report/summary.json)、[逐任务 CSV](repair50_evidence/report/tasks.csv) | 离线重新核算的总分、逐任务结果、用量和新增/丢失 |
| [案例索引](repair50_evidence/cases/index.json) | 三项新增成功、三项最终失败的上下文/补丁/日志；18 项准入异常日志 |
| [审计脚本](repair50_evidence/audit.py)、[输入哈希及原路径](repair50_evidence/inputs.json) | 纯标准库核算；核对文件完整性、评分条件及用量一致性 |
| [实验协议](coverage-full-repair-v1-protocol.md)、[原结果报告](coverage-full-repair-v1-results.md) | 当时的执行范围与完整结果，保持原样 |

原始报告按字节复制，保留历史绝对路径；无需这些路径存在即可做报告核算。涉及上游源码的摘录附有[来源与许可证](repair50_evidence/NOTICE.md)。哈希用于检查一致性，不是第三方认证。

## 2. 对照配置：不是从原始 CoreCoder 直接跳到 94%

直接基线是 **2026-10-09 的 `current-full-repair-v1`（43/50）**，优化轮是 **2026-10-10 的 `coverage-full-repair-v1`（47/50）**。
基线已包含代码检索、公开测试反馈和最多一次修正；不能把这一组提升解释为“额外加了一轮”。
早期 `25/50 → 32/50`、无思考/高思考 `28/50 → 43/50` 来自其他实验，不合并成同一对照。

| 两轮相同条件 | 值 |
| --- | --- |
| 模型请求 | DeepSeek `deepseek-flash`，high reasoning，thinking enabled |
| 采样与输出 | temperature 0，top_p 0.95，JSON object；执行器仍须校验 JSON 内容 |
| 每项调用 | 初次生成 + 最多一次公开反馈修正，共最多 **2 次**；不是 20 轮工具循环 |
| 每项预算 | 累计 60,000 Token；单次输出最多 32,768 Token，**包含思考** |
| 上下文 | 请求上限 65,536 Token；检索正文最多 5 段、6,000 字符 |
| 超时 | 工作进程 1,200 秒；API 480 秒、SDK 重试为 0；单组测试 15 秒 |
| 数据与评分 | 同一 50 项、原始缺陷源码、允许修改范围、公开/冻结检查及独立评分 |
| 特殊公开契约 | `click-flag-envvar` 两轮均有；不是本轮新增的增益来源 |

配置还保存了通用字段 `max_rounds=12`，但本实验走结构化补丁执行器，实际调用上限由上述两阶段流程控制。
109 次 API 响应记录的 `system_fingerprint` 相同；云端模型别名和 fingerprint 均不能替代固定权重与环境快照。

## 3. 优化改动：先修复上下文缺失，再约束补丁

| 具体问题 | 实际改动 | 代码证据 |
| --- | --- | --- |
| 描述写 `HelpFormatter.write_usage`，过滤时却只拿 `write_usage` 比较，目标函数被排除 | 同时识别限定名和叶子名，避免已定位符号被过滤掉 | [v1](experiments/public_api_context_v1.py) → [v2](experiments/public_api_context_v2.py) |
| 5 个片段名额被辅助方法占用；`with_resource` 缺 `__exit__`，相等性缺哈希实现 | 先为明确修复目标及关联协议方法预留位置，再补可选上下文；超过既定预算就明确失败 | [coverage_context_v2](experiments/coverage_context_v2.py) |
| 模型返回空 edits、相同 old/new 或不能应用的锚点，仍消耗修复机会 | 要求非空实际修改，校验允许路径、证据哈希、唯一原文锚点；在暂存副本应用并编译后发布 | [constrained_patch_v1](experiments/constrained_patch_v1.py)、[补丁应用](../evals/symbol_context.py) |

省略超长文档字符串时保留签名及主体代码，是否完整符号由 `complete_symbol` 标记，不能笼统声称所有片段都是完整函数。
反馈修正仍最多一次，使用当前候选上下文；公开/冻结检查不通过则回滚。模型输出补丁请求，执行器负责校验、修改和运行测试。
本实验调用模型时 `tools=[]`，输出 `{edits: [{file, old, new}]}`；不能把这一轮说成模型主动搜索、执行测试的 Tool Calling 实验。

这些改动同时进入优化轮，因此只能报告**整套改动的观察收益**；没有消融实验，不能给某个模块单独分配提升百分点。

## 4. 怎样评分，为什么不是“模型说修好了”

```text
上游固定缺陷版本 → 准入检查 → 准备公开上下文 → 模型生成结构化补丁
       → 执行器应用 → 公开/冻结检查 → 必要时一次反馈 → 保留或回滚
       → 独立进程检查最终源码的 Target + Controls → 记录是否 accepted
```

- **准入：**原始版本 Target 实际运行且失败、Controls 通过；上游参考修复版本 Target 和 Controls 均通过。不是随意往源码注入错误。
- **公开检查：**Reproduce 验证目标现象，Preserve 检查约定正常行为；失败信息允许反馈给模型。冻结检查用于维持既定约束。
- **独立评分：**Target 和 Controls 不进入候选补丁生成请求，参考修复不进入模型上下文；评分针对最终产物执行。
- **accepted：**工作流 completed、公开检查通过、冻结检查通过、要求的最终检查通过、独立 Target/Controls 通过且无修改范围违规，缺一不算成功。
- **通过含义：**退出码为 0、不超时、实际执行测试，且无失败、错误、跳过、expected failure 或 unexpected success；缺测试、环境故障和超时不能当通过。

准入原始 Target 有 **32 项断言失败、18 项 ERROR**。ERROR 不必然是环境故障：例如空迭代器触发 `StopIteration`、常量退避触发 `ZeroDivisionError`。
[18 份原日志和异常摘要](repair50_evidence/cases/index.json)已保留并检查，均涉及目标调用；仍需结合调用栈、正常行为和参考版本判断，不能仅按异常类型自动分类。
历史准入接受这类缺陷异常，与后续新 Issue 导入的更严格准入规则不要混用。

这些检查是项目编写的缺陷复现和正常行为测试，**不是各上游仓库完整测试套件**；测试作者接触过上游修复，存在选择偏差。
历史评分采用本地隔离工作区与 Python 子进程，**没有使用后来加入的 Docker 沙箱**；独立进程也不保证同解释器中的测试完全防篡改。

## 5. 结果与成本

| 指标 | 基线 | 优化轮 |
| --- | ---: | ---: |
| 通过 | 43/50（86%） | 47/50（94%） |
| API 调用 | 55 | 54 |
| 输入 Token | 111,401 | 112,542 |
| 输出 Token（含思考） | 604,365 | 536,051 |
| 总 Token（含失败任务） | 715,766 | 648,593 |
| 最终 Controls 通过 | 50/50 | 50/50 |

净增 4 项、**+8 个百分点**；总 Token 差值 −67,173，变化 −9.38%。输入 Token 实际略增，主要减少的是输出；不能表述为“检索使输入 Token 降低 9.38%”。
没有冻结价格或账单，**不换算人民币或美元成本**。最终 Controls 50/50 包含拒绝补丁后回滚到原始源码的任务，不代表每个候选均无回归。
两轮共 100 次任务运行、109 次 API 调用，仍只有 50 个不同任务。

| 仓库 | 任务数 | 基线通过 | 优化通过 |
| --- | ---: | ---: | ---: |
| Click | 10 | 6 | 9 |
| ItsDangerous | 3 | 3 | 3 |
| Toolz | 6 | 6 | 6 |
| Boltons | 7 | 7 | 7 |
| More-itertools | 24 | 21 | 22 |

配对结果：**共同通过 42、新增成功 5、成功丢失 1、共同失败 2**。完整名单见 [CSV](repair50_evidence/report/tasks.csv)。
新增成功为 `click-usage-empty`、`click-resource-exception`、`click-invoke-missing`、`more-reverse-empty-range`、`more-range-equality`。

## 6. 三个可以展开讲的成功案例

| 任务 | 原先缺什么 | 优化轮证据与结果 |
| --- | --- | --- |
| click-usage-empty | 五段上下文没有 `HelpFormatter.write_usage`，两次返回未修改源码 | [上下文](repair50_evidence/cases/click-usage-empty/candidate/context-selection.json)补入目标；[补丁](repair50_evidence/cases/click-usage-empty/candidate/verification/patch.diff)处理空 args，独立验收通过 |
| click-resource-exception | 有 `Context.with_resource`，缺处理退出和异常传播的 `Context.__exit__` | [上下文](repair50_evidence/cases/click-resource-exception/candidate/context-selection.json)补入退出方法；[补丁](repair50_evidence/cases/click-resource-exception/candidate/verification/patch.diff)传递异常并处理抑制返回值，通过约定检查 |
| more-range-equality | 有 `__eq__`，缺与相等性契约相关的 `__hash__`；基线输出截断 | [上下文](repair50_evidence/cases/more-range-equality/candidate/context-selection.json)保留二者；[补丁](repair50_evidence/cases/more-range-equality/candidate/verification/patch.diff)同时处理单元素范围的相等性和哈希，通过验收 |

这些案例支持“补齐上下文后观察到成功”的解释，不证明单独补齐这一段就必然成功，也不保证补丁覆盖所有上游边界条件。

## 7. 三项失败必须一起展示

| 任务 | 最终状态与证据 | 下一次可以检验的假设，尚未证明有效 |
| --- | --- | --- |
| click-shared-default | 2 次调用、58,249 Token；补丁能应用，但[公开复现仍失败](repair50_evidence/cases/click-shared-default/candidate/initial-public/Reproduce.stderr.txt)，最终回滚 | 当前上下文偏向 Command 方法，可能仍缺共享参数对象的生命周期信息；应先核对调用链，不能只追加提示 |
| more-negative-range-slice | **基线成功、优化轮失败**；1 次、34,535 Token，finish_reason=length；输出上限 32,768 Token 全部用于思考，没有完整补丁 | 研究思考/输出分配或截断恢复；必须另立协议，不能无上限重试后冒充本轮成绩 |
| more-range-membership | 两轮均失败；优化轮 1 次、34,221 Token，同样输出截断 | 补入 index 仍不足；区分上下文与生成阶段瓶颈，不能声称新检索已解决 |

三项共消耗 **127,005 Token，占优化轮约 19.6%**。两项截断来自原始调用记录，不是根据失败结果猜测。
失败补丁回滚后最终 diff 可能为空；不要把空 diff 理解为未调用模型。[案例索引](repair50_evidence/cases/index.json)保留基线/优化轮的相应上下文与最终 diff。

## 8. 如何现场核算

在仓库根目录运行，不安装依赖、不读取 API Key、不进行模型推理或测试评分。输出目录必须是新的，避免覆盖证据：

```powershell
python -B -S docs/repair50_evidence/audit.py --output .tmp/repair50-review-01
```

它核对输入和摘录哈希、50 项完整性及配对、两轮配置一致性、原始测试计数与通过标记、最终接收条件、每次 provider 用量与合计，输出 `summary.json` 和 `tasks.csv`。
这证明**记录和计算一致**，不能独立证明原执行现场可信，更不能替代重新运行测试。

原工作机还保留 `.tmp/real-defects` 时可额外执行：

```powershell
python -B -S docs/repair50_evidence/audit.py --output .tmp/repair50-review-local-01 --verify-local-assets --source-root .
```

2026-10-19 本机离线核对了协议记录的 **24 个文件、244 份去重目录快照**。此项不执行源码，也不重新评分。
新克隆没有被忽略的 `.tmp` 原始源码和评分材料时，只运行第一条命令；它不是原始实验的端到端重跑命令。
历史依赖与模型权重没有完全锁定，因此即便重新推理，也不能保证逐位复现。本机核对范围仅限已记录输入，不代表整个运行环境都被哈希覆盖。

证据脚本的回归命令：

```powershell
python -B -m pytest tests/test_repair50_evidence.py -q -p no:cacheprovider --basetemp=.tmp/pytest-repair50-review
```

本次 **9 项通过**，覆盖接收标记、用量、重复任务、配置、参考验收及日志摘录被改动时拒绝核算，以及不加载已安装依赖的 CLI 运行；Ruff 检查通过。目录内 `.gitattributes` 禁止 Git 转换原始记录和摘录的换行符，防止 Windows 克隆后字节哈希失效。

## 9. 面试怎么说

**90 秒回答：**

> 我做的是 Issue 修复与验证系统，重点是让模型获得正确代码上下文，并让每次修复结果能被复核。
> 我整理了五个 Python 仓库的 50 项真实来源缺陷，保留缺陷版本、参考版本和独立验收测试。
> 排查失败记录时发现，符号过滤把限定名和短名混用，导致目标方法被删掉；另一些任务拿到了入口，却没拿到退出或哈希等关联方法。
> 我修正匹配，并在固定的五段、六千字符内优先保留目标及关联方法，同时拦截空补丁、无效锚点和无变化修改。
> 在模型、高思考模式、两次调用上限和评分不变的两轮完整对照中，通过数从 43 提高到 47，Token 降低 9.38%。
> 其中新增成功五项、丢失一项，我没有隐藏退步。剩下两项输出截断、一项逻辑修复失败，都留下了调用和测试证据。
> 这是已知任务池的单次结果，不代表陌生仓库也有 94%，检索和补丁约束的贡献还需要消融和新留出集验证。

| 常见追问 | 回答边界 |
| --- | --- |
| 不就是再问一遍模型？ | 两轮都最多两次；本轮主要改代码选取和补丁执行约束，实际调用 55 → 54 |
| 如何证明不是换了模型？ | 请求别名、思考、采样、预算和记录 fingerprint 相同；云模型权重不能保证不变，因此仍有混杂因素 |
| 有没有数据泄漏？ | 独立测试/参考修复不进入请求，但作者接触过上游修复、任务池也已用于调优；不能宣称严格盲测 |
| 每个优化贡献多少？ | 目前没有分别消融，不能拆分；能展示具体上下文差异、补丁和配对结果 |
| 为什么比现成 Coding Agent 好？ | 没有与 Codex/Claude Code 做公平对照；贡献是约束范围内的修复、验证和证据工程，不宣称通用能力超过它们 |

**简历可用一句：**修正限定符号匹配，优先保留目标及关联协议方法，并增加非空补丁与唯一锚点校验；在固定模型与预算的已知 50 项完整对照中，通过数 43→47（86%→94%），新增成功 5 项、丢失 1 项，总 Token 降低 9.38%。

**限制：**任务小且仓库分布不均；历史标签虽有 30 development / 20 heldout，但最终池已反复检查，20 项不能再称未见留出集。
没有多随机种子重复、严格消融、真实用户收益或生产 SLA。后续应先冻结新任务、验证评分质量，再开展预注册对照；当前证据包不追加这些实验。
