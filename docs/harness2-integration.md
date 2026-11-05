# Harness² 与本项目的接入

2026-11-05 后续：[控制端 Patch Validator](patch-validator-20261105.md)完成独立入口和四份制品验收。Harness² 无权修改验证器；公开检查与后验 Target/Controls 分开，Langfuse 仅发布公开摘要。本轮模型调用 0，尚未接入 Agent 反馈循环，不能解释为自主策略已提高修复率。

2026-11-04 后续：完成 [首轮失败复盘](harness2-review-20261104.md)，纠正原代码已有 iteritems、候选重复输出及测试工具边界。增加显式 `--context-policy` 的三布尔配置层，已完成无模型验收；不带开关仍保持下面首轮的两文件权限。下列真实模型结果属于扩展前版本，未重跑。

随后完成 [固定指导、只开启读取去重的三对真实运行](harness2-context-paired-20261104.md)：同一任务两组均 0/3，无补丁、重复读取停止；原生 Token 减少 1.82%，没有修复收益。该固定配置消融未重新调用 Harness² 策略生成，不改默认配置或完整 50 项基线。

## 分工

最新完成 [三组件自主PPC试验](harness2-autonomous-20261104.md)：自主修改两份指导及Context配置，最终有补丁但目标仍失败；38次调用、256,704 Token。传输改为可逆共享后只恢复后置阶段，不重跑四次修复；经验审查拒绝复用。

已有 Langfuse 负责保存、展示和核对轨迹、用量与评分；当前自有 Agent 的完整本地基线为 **21/50（42%）**。
Harness² 在执行器外增加一个改进流程：根据可见任务和执行行为提出运行策略改动，探测改动，再合成最终策略。模型权重不变，也不把独立测试答案当作改进信号。

```text
同一公开 Issue + 固定源码
  → 原策略执行 base1
  → 提议通用改动 inv1、领域改动 dom1
  → 各用一份新工作区运行自有 Agent
  → 根据行为差异合成 agg1 → 再执行
  → 采纳最终策略、提取有证据的经验
  → 此时才独立评分 base1 / inv1 / dom1 / agg1
  → Langfuse 关联编排、真实推理 Trace、用量与最终验收
```

`k=1` 并行模式包含 **4 次执行**和 **3 个提议/合成阶段**，另有一次采纳后的经验提取。
官方核心在这个配置下直接采纳唯一合成结果；**不会读取隐藏测试分数后挑四份补丁中分数最高的一份**。最终策略可能没有收益，也可能退步，必须保留所有尝试与成本。

## 当前实现范围

- 固定上游 commit `6868817518876de8fd170c6a8354daca273b6191`，校验 41 个源码/许可证/元数据文件的 SHA256；Apache-2.0 许可证保留在下载目录。
- 复用官方 `run_domain`、Propose–Probe–Compose、采纳、反思和经验库；新增 `BenchmarkAdapter`、自有执行器和本地 JSON 编辑器。不是自行模拟一套同名算法。
- 执行器继续使用自有 checkpoint Agent、Qwen3.5:27b、think=false、不按 Token 量停止；原有轮数、时间、工具校验和 Docker 评分边界不变。
- 编辑器仅能修改 `systemprompt.md` 与 `tool_descriptions/tool_guidance.md`，每份最多 4000 字符；不能编辑模型配置、权限、评分器、测试、脚本、插件或仓库源码。
- 原提示与工具契约由执行层保留；改进提示作为附加指导加入。基线两份指导均为空，不额外改变原模型输入。
- 本地编辑器每个阶段接收任务、Harness 文件及完整可见行为记录，返回声明式 JSON；不会运行模型生成的代码。仓库原文不整库内联；完全重复的证据保留一份全文，其余位置使用显式引用，不丢内容。唯一证据正文限 160k 字符，超出报错，不静默裁剪。每个编辑阶段最多两次 JSON 格式校验/修正，失败消耗照常计入。
- 调用官方核心时沿用其 OpenCode 文本组件 schema 名称，但真正执行器命名为 `cc`；不启动 OpenCode、Codex、Vertex 或付费 API。
- 官方面向 Linux/Python 3.12–3.13。本机控制器使用已有 Python 3.12，补充 Windows 文件锁、路径与占位文件兼容；上游源码字节不修改。这不是官方完整 Benchmark 环境的 Windows 支持声明。
- 上游源码、新制品、临时文件均放 D 盘；执行器复用已有 conda 环境，不改装其 Python。Langfuse 发布使用现有 D 盘依赖和本地凭据文件，不把凭据发给模型。

当前入口是**研究用、单任务、并行 k=1 的可选接入**；不替换生产 CLI/API、不运行新的完整 50 项、不把接入验收称为修复率提升。

## 已完成的验收

1. **官方无模型 demo：**并行与顺序模式，`k=2`、2 个账目任务，28 次真实 Python 脚本执行、32 次脚本编辑/选择/反思，2 项均完成；第二项读取此前任务的经验库。真实模型调用 0。
2. **自有执行器合成烟测：**官方核心完成 base/invariant/domain/composition 四次自有修复执行，合成任务的目标与正常行为测试均实际执行并通过；编辑器和响应为脚本，真实模型调用 0。Langfuse 编排 Trace 5 个普通节点、0 个 Generation，回读通过。
3. **测试：**10 项边界/证据/并发测试在 Python 3.12 通过，官方 `test_workflow.py` 7 项通过；现有环境相关回归 71 passed、4 skipped（包含 3.12 专属用例及未安装的可选 mini-SWE 依赖）。Ruff 通过。未重跑整仓测试。

无模型验收期间修复了 Windows 组件路径/占位文件、并行调用输出目录冲突及合成检查文件名适配。失败制品保留在 D 盘旧目录，没有模型效果数据被选择性覆盖。

## 本地真实模型试验

固定 `toolz-join-unmatched`，一项、并行 `k=1`；编辑器和执行器都使用本地 Qwen、关闭 thinking。
执行前验证模型 digest、评分镜像、42% 基线源码以及任务/独立检查哈希。评分在采纳、反思完成后才执行，不反馈给编辑器或经验库。

运行目录 `.tmp/harness2-toolz-pilot-20261104-v2`。独立评分结果如下，每组实际执行 1 项 Target 和 1 项 Controls；检查范围是自编目标/保持性检查，非 Toolz 整套上游测试。

| 阶段 | 自有 Agent 行为 | Target | Controls | 执行器调用 / Token |
| --- | --- | --- | --- | --- |
| base1 原策略 | 重复读取停止，无补丁 | 失败 | 通过 | 7 / 25,600 |
| inv1 通用策略 | 重复读取停止，无补丁 | 失败 | 通过 | 6 / 23,255 |
| dom1 领域策略 | 生成补丁 | 失败 | 通过 | 5 / 18,701 |
| agg1 合成策略，最终采纳 | 生成补丁 | 失败 | 通过 | 5 / 18,701 |

**结果：完成接入，未修复该缺陷。**最终补丁仍调用不存在的 `iteritems`，触发 `NameError`；生成的指导还包含未提供的 `python_join_repair` 技能及实际接口没有的 `how='left'`。JSON 合法不等于指导事实正确，策略生成后仍需要源码核对与独立验证。经验编辑器返回 `null`，没有新增经验条目。不能由“生成了补丁”推断修复成功，也不能从这一项推断完整任务池提升。

完整第二次试验含 4 次执行、3 个提议/合成阶段、1 个经验提取阶段，合计 **28 次模型调用、196,025 Token**，包括一次 JSON 格式修正。首次试验 `.tmp/harness2-toolz-pilot-20261104` 因 `notes` 错放入文件字典而中断，另消耗 **9 次调用、54,283 Token**，完整保留。两次合计 **37 次调用、250,308 Token**；云 API 费用为 0，本机计算成本未计价。

第二次试验在完成四份补丁及采纳后，经验提取遇到证据传输检查：原始 188,474 字符中，唯一正文 92,721 字符。增加无损重复引用后，通过 `--finish-existing` **只恢复经验提取、独立评分和发布**，复用原四次执行。原始 `core-result.json` / `summary.json` 的 partial 失败记录保留；`recovery-protocol.json`、`recovery.json` 说明恢复边界，不伪装成首次即成功。

Langfuse 编排 Trace 回读 **9 个普通节点、0 个 Generation**，通过元数据关联 8 条真实推理 Trace；另含首次失败的 3 条推理 Trace，共 11 条、37 个 Generation 的 Token 与本地原生记录核对一致。编排摘要不重复记模型用量。[打开本地编排 Trace](http://127.0.0.1:3300/project/corecoder-issues/traces/a5a059e7ed28a07b3c89b21d672ac236)。

原 42% 基线的 330 份证据及实现哈希复核未变。本轮不更新完整 50 项成绩。可提交证据与校验清单见 [归档清单](harness2-20261104.json)、[证据目录](harness2_20261104/)。

## 使用

需要已有 `corecoder` 环境、Ollama 模型、Docker 小镜像和本地 Langfuse。控制器需 Python 3.12/3.13，以下使用本机已有运行时，不在 C 盘安装任何包：

```powershell
conda activate corecoder
cd D:\project_other\CoreCoder
$controller='C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:CORECODER_AGENT_PYTHON=(Get-Command python).Source
$env:PYTHONPATH="$PWD"
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:TEMP="$PWD\.tmp"; $env:TMP=$env:TEMP
$env:CORECODER_HOME="$PWD\.tmp\harness2-state"
$env:NO_PROXY='127.0.0.1,localhost,::1'
$env:CORECODER_LANGFUSE_ENABLED='1'
$env:CORECODER_LANGFUSE_ENV_FILE="$PWD\.tmp\langfuse-local\.env"
$env:CORECODER_TEST_BACKEND='docker'

# 首次没有固定源码目录时执行；目录已存在会拒绝覆盖。
python -B -m integrations.fetch_harness2

# 三种命令均使用新输出目录：
& $controller -B -m integrations.harness2 --demo --output .tmp/h2-demo-new
& $controller -B -m integrations.harness2 --smoke --output .tmp/h2-smoke-new
& $controller -B -m integrations.harness2 --task toolz-join-unmatched --output .tmp/h2-live-new

# 可选配置层的无模型验收；不是新的修复率实验：
& $controller -B -m integrations.harness2 --context-policy --smoke --output .tmp/h2-context-smoke-new

& $controller -B -m unittest tests.test_harness2 -q
```

官方 demo 和合成烟测不使用模型；只有第三条实际调用本地 Ollama。
目录已存在会拒绝覆盖，不自动整轮重试；上游阶段内部仍保留自身的有效性检查与有限回退。真实试验中若发生接入错误，先保留已消耗的调用与制品，再决定如何恢复。
`CORECODER_AGENT_PYTHON` 指向原 conda 环境，控制器由单独的 `$controller` 指定，两者无需使用同一 Python 版本。

仅对固定 Toolz 任务已经完成采纳、尚未开始独立评分的目录，提供 `--finish-existing <原输出目录>`。按原协议恢复两文件或Context模式，校验原补丁和组件哈希，只恢复经验、评分和交付，不重新执行提议、探测或合成；已评分目录拒绝再次恢复。它不是通用断点续跑命令，已完成的恢复无需重复运行。

## 如何阅读结果

- `protocol.json`：版本、唯一任务、可改组件、基线与实现哈希。
- `runs/issue-cc-agg1/<task>/summary.json`：阶段、回退、采纳和经验。
- `executions/`：每次自有 Agent 的补丁、动作、原生 Token、Trace 链接。
- `editors/`：每次真实提议/反思的输入、JSON、原生 Token 和 Trace；脚本模式不计模型用量。
- `grading/grading.json`：采纳结束后的独立 Target/Controls；从不进入改进上下文。
- `report.json`、`publication/langfuse.json`：完整成本、采纳结果、编排 Trace 回执；编排摘要使用 Span，真实模型调用保存在对应原始 Generation 中，不重复伪造。

应先学会解释“改了哪份指导 → 哪个执行行为改变 → 最终补丁是否通过 → 多花了多少执行”，再考虑开放记忆、技能或脚本组件。现有 50 项均为已知任务，不声称由此得到未见任务泛化结果。

参考：[官方仓库](https://github.com/google-research/harness2)、[固定版本](https://github.com/google-research/harness2/tree/6868817518876de8fd170c6a8354daca273b6191)、[官方实验说明](https://github.com/google-research/harness2/blob/6868817518876de8fd170c6a8354daca273b6191/docs/EXPERIMENTS.md)。
