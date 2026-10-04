# fixed-evidence-v1：公开证据一次性补丁诊断

更新：2026-10-04。**独立诊断协议，不是 Agent、RAG 或去重策略效果对照。** `--mode fixed-evidence` 实际调用模型，但报告 benchmark_eligible=false。

## 目的与实现

将缺陷描述、所有允许修改的源码、docs 下公开 Markdown 及 README.md 一次性提供给模型，判断证据已提供且无需工具定位时，能否生成完整修复。所有允许源码均提供，不按参考修复挑选相关文件。提供路径、完整正文与 SHA256；不提供可见/隐藏测试、参考补丁、相关文件标签或父进程验证结果。

只进行一次应用层请求，无工具 Schema、Agent 系统提示、任务计划、上下文压缩或测试反馈。要求输出 JSON edits，每项包括 file/old/new；不自动剥离 Markdown、补全 JSON 或追加修复轮次。保留原始响应，格式失败记 invalid_patch，不能直接当作业务理解失败。底层既有提供商失败重试仍可能存在，其费用未知；这里的一次是逻辑 LLM 调用。

全部编辑先在内存验证：字段、数量、允许路径、符号链接、证据版本、唯一原文匹配。任一项无效则不写入；写入时的 I/O 故障不构成跨文件事务，失败候选仍保存并由独立验证器拒绝。候选 Python 与旧人工任务一样在宿主验收，本模式不是恶意代码沙箱。

父进程继续生成新验收副本、检查修改范围、执行原目标与回归测试。正常生成补丁不等于修复成功。该模式拒绝混用搜索、上下文或契约提示策略。协议改变了证据供给、Prompt、工具与调用流程，任何成功都只能说明当前公开证据诊断下的补丁能力，不能称为 Agent 成功率提升。

120,000 字符硬限制与现有输入/输出预算预检均保留，超出时显式失败，无静默截断。固定输入在请求中不包含工作区绝对路径，重复任务的 Prompt 哈希应相同。

## 预先固定的运行

pagination-cursor 与 lease-lifecycle 各三次，共六次，使用同一代码版本、干净工作区、原模型和预算：Ollama qwen3.5:27b、temperature=0、reasoning_effort=none、Token 30,000、输出 2,048、上下文估算 16,000、Worker 180 秒、测试 15 秒。轮数参数对该单请求协议不生效，报告配置仍保存；不将结果与旧工具循环当作公平因果对照。

保留全部输出和失败，不选择性重跑。分别报告正常补丁/格式失败、独立目标与回归、实际用量和修改范围。六次仍只有两个独立人工任务，不用于泛化或显著性判断。

## 复跑

```powershell
python -m pytest tests/test_fixed_evidence.py -q
python -m pytest tests -q
python -m evals --suite evals/fixtures/localization-v1 --task pagination-cursor --mode fixed-evidence --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --repeat 3 --output .tmp/evals/fixed-evidence-v1/pagination-cursor
python -m evals --suite evals/fixtures/retrieval-overlap-v1 --task lease-lifecycle --mode fixed-evidence --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --repeat 3 --output .tmp/evals/fixed-evidence-v1/lease-lifecycle
```

新实验请使用新目录。返回码 1 表示未全部验收通过，需检查具体状态。报告新增 evaluation_protocol，Worker 保存公开证据 manifest、Prompt 哈希及原响应 diagnostic-response.txt；父进程仍保存补丁和独立测试。产物位于忽略的 .tmp，需独立备份。

## 已执行结果

| 任务 | 独立验收 | 每次输入 / 输出 / 总 Token | 每次逻辑调用 | 公开证据文件 |
| --- | --- | --- | --- | --- |
| pagination-cursor | 3/3 通过 | 1,253 / 341 / 1,594 | 1 | 8 |
| lease-lifecycle | 3/3 通过 | 2,161 / 568 / 2,729 | 1 | 14 |

六次均返回可解析且可应用的 JSON，无格式失败、预算终止、基础设施故障或缺失 usage。每次目标 4 项、可见回归 2 项通过；没有工具调用、没有测试反馈后的模型重试。同任务三次公开证据 manifest 与 Prompt 哈希相同，实际 Token 相同；三次重复不等于三个独立缺陷。

分页同时修复 query.py 的复合键比较与 paging.py 的续页游标。租约同时修复 acquire.py 的时间单位、lookup.py 的租户定位及 expiry.py 的相等到期边界。验收仅代表满足现有目标与回归范围，不证明所有未测试行为正确。

原始汇总：

- [pagination 三次](../.tmp/evals/fixed-evidence-v1/pagination-cursor/summary-6cb5ee788b.md)
- [lease 三次](../.tmp/evals/fixed-evidence-v1/lease-lifecycle/summary-e736c7c080.md)

报告全部 benchmark_eligible=false。本次生成源码哈希 `87a22ce922f10383f3fcc1bdde993741e01774e270eb929e50986fe8cb936cd4`。不能将 6/6 与之前 Agent 的 0/4 直接称为公平成功率提升或推断 Token 降幅，因为完整证据、系统提示、工具 Schema 与调用协议同时变化。

## 换行修正与离线重放

检查原始补丁时发现 Windows 文本写入会把已有 CRLF 再次翻译为 CRCRLF，造成额外空行；租约的 renew.py 虽无业务变化也被计入格式变更。已改为按 UTF-8 字节写入，保留模型提供的换行，并跳过字节完全相同的编辑。

使用六份原始模型输出，在原缺陷版本的新副本中通过修正后的写入器重新应用，并由同一父进程独立验证器验收，**6/6 仍通过，没有追加模型调用**。分页实际修改两文件，租约三文件；多余 renew.py 变化消失。重放是离线应用验证，不是新的六次模型运行。

重放记录位于 `.tmp/evals/fixed-evidence-v1/newline-replay/summary.json`，各项保存原 run_id、输出 SHA256、当前源码版本、补丁及测试。修正后源码哈希 `82191c1189a93d51aa33ebaa9ae9e12d4580571274669ede038f5df960f43b2a`。原始 live 报告保留原版本和用量，不重写历史。

## 验证与下一步

13 项新增测试覆盖证据隔离、路径/字段/原文验证、无效后续编辑不先写入、版本变化、格式失败、模式隔离、父进程独立评分、CRLF 与无变化编辑。最终全量 **289 passed、1 skipped，47.95 秒**，Ruff 通过；Windows 符号链接测试跳过。

诊断说明模型在完整公开证据条件下能修复这两个任务，不能再把此前失败简单归为“模型不会修”。工具循环中的定位、证据组织、提示与执行开销值得优先研究；当前数据不能进一步分离各因素的贡献，也不能证明大仓库具备相同补丁能力。

下一步开发**有界的证据构建 → 结构化补丁生成 → 独立验收**执行管线，将证据构建与补丁生成解耦。先固定该协议和预算，再在同一管线内比较检索与上下文策略；与旧自由工具循环的比较单独作为端到端系统对照。一次性提供全部源码仅保留为小任务能力诊断，大仓库仍需要限额检索与可靠上下文。
