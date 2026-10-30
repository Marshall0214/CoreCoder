# 符号读取、结构化编辑错误与恢复

## 交付范围

新增 `symbol-recovery-v1`：模型可用 JSON 动作读取当前 Python 符号、申请补丁和结束任务。
锚点/版本失败后，执行器强制要求重新读取受影响文件，随后才允许再次编辑。
公开测试失败时可以继续读取、修正；只有约定公开检查通过且存在净修改，才保留待人工审查的补丁。
不调用 DeepSeek，不开启 thinking；历史 50 项报告及评分协议保持原样。

这不是完整自主搜索系统：只读取管理员允许修改的文件，尚无 search_code、任意 read_file、Shell 或网络工具。
模型可以利用初始片段和公开测试中的符号名；支持读取函数、类以及模块级赋值和导入声明，找不到支持的声明时得到有界候选列表。

## 与旧入口的关系

| 入口 | 默认行为 |
| --- | --- |
| `python -m repairflow repair-issue` | 新 `symbol-recovery-v1` |
| CLI 显式 `--workflow patch-v1` | 旧初次生成 + 一次修正 |
| Python `issue_repair.execute()` 不传 workflow | 保留 `patch-v1`，兼容已有调用与历史脚本 |
| 可信 bundle 的 `run`、旧 evals、历史响应 | 不改动，不自动获得新工具循环 |

新报告 schema 为 `prepared-issue-symbol-recovery-v1`；配置、工作流、源码模块哈希保存在 `provenance.json`。
两种流程结果不能混作同协议成绩。新入口的 HTTP 审批接入仍未完成。

## 重试策略及参考

2026-10-23 核对的上游源码：

- [Aider](https://github.com/Aider-AI/aider/blob/main/aider/coders/base_coder.py)：`max_reflections=3`，限制一次用户请求后的反思修正；不是整个会话只运行三步。
- [SWE-agent](https://github.com/SWE-agent/SWE-agent/blob/main/sweagent/agent/agents.py)：`max_requeries=3`，针对格式错误、阻止的动作或 Shell 语法等错误重询；不是所有补丁的总次数。
- [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/agents/default.py)：独立设置步数、费用、墙钟时间与连续格式错误；所查默认配置连续格式错误为 3，总步数为 0（不限制），不能脱离其费用限制理解为无限免费执行。

本项目借鉴“总预算 + 分类停止条件”，以下默认值是本项目的工程选择，尚无实验证明最优：

| 配置 | 默认值 | 含义 |
| --- | ---: | --- |
| `--max-steps` | 20 | 所有模型动作总数，包含读取、格式错误与 finish |
| `--max-edit-attempts` | 6 | 补丁申请总数，包含被拒绝及缺少必要读取的申请 |
| `--max-consecutive-errors` | 3 | 连续工具/动作错误达到该数即停；成功读取或有效编辑会清零 |
| `--max-repeated-actions` | 3 | 同一源码状态下，相同动作最多执行三次；第四次阻止，间隔其他动作也累计 |
| 累计 Token | 60,000 | 估算预检与返回用量记账，非服务商计费硬上限 |
| 单次输出 | 4,096 | 新协议使用短 JSON 动作；旧流程仍为 32,768 |
| 上下文 | 65,536 Token | 继承现有预算预检 |
| 任务期限 | 1,200 秒 | 阶段间检查；Ollama 单次最多剩余时间与 480 秒 |

四个次数参数必须为 1–100 的整数。20 步不等于 20 轮修改；实际常先被 Token、时间或重复错误限制停止。
脚本模式没有实测用量，仍按每次请求预留额度保守记账，不伪造 Token 数据。

## 工具协议

模型每次返回一个动作；由执行器解析和调度，并非 Ollama 原生 function calling：

```json
{"action":"read_symbol","arguments":{"path":"src/pkg/__init__.py","symbol":"Class.method","offset":0}}
```

`offset` 为符号内部的字符偏移，默认 0。返回当前字节哈希、限定符号、行范围、原文、`complete_symbol`、`next_offset`。
包括装饰器、函数声明、文档和主体；保留原始 CRLF。只做 AST 静态解析，不导入仓库模块。
结果中的 `kind` 区分 `function`、`class`、`assignment`、`import`，`resolution=static_declaration` 表示只读取声明，未求值或确认运行时绑定。
模块赋值支持普通、带类型注解、链式和解包形式；仅注解而未赋值时 `value_present=false`。
导入按当前文件实际绑定的名称查找，包括别名；`import_source` 返回 `module/name/level/followed=false`。
例如读取 `strip_ansi` 只返回 `from ._compat import strip_ansi`，不返回 `_compat.py` 的实现，也不扩大允许文件范围。
通配导入、动态赋值、属性/下标赋值、函数局部和类内赋值不作为模块绑定解析。
条件分支内的声明仅是静态可能性；多次同名声明（包括 try/except 的导入）返回歧义，不猜测分支或最后实际绑定值。
短名对应多个符号或限定名重复定义时返回 `symbol_ambiguous` 及带行号的候选，不擅自选第一个。
每页最多 6,000 字符，过长时显式返回下一页位置；末页不代表整个符号已在这一页完整出现。
最多保留 24,000 字符可编辑证据，先淘汰旧片段。跨页锚点若未完整出现在任一片段中，继续拒绝，模型应选择较小局部锚点。

历史观察默认 `--observation-policy full`，可显式启用 `compact-v1`：历史读取只保留元数据与 `content_available`，补丁 old/new 只保留长度和哈希，错误与测试反馈原样保留。当前源码仍由 `fragments` 提供，旧版本或被淘汰读取不能冒充当前证据；完整动作、回答和 Trace 不压缩。该选项仅适用于 `symbol-recovery-v1`，详见[第 1 轮对照](compact-observations-20261029.md)。

```json
{"action":"apply_patch","arguments":{"edits":[{"file":"src/pkg/__init__.py","old":"    return x + 1","new":"    return x + 2"}]}}
```

也兼容旧脚本 `{ "edits": [...] }`，采用完全相同的校验，不额外授予权限。
所有编辑先在暂存副本校验，路径/证据版本/原文唯一性/已读范围及语法均通过才发布。
改动文件的旧证据随即失效；后续修改这些文件必须重新读取。有效补丁自动触发原可信 Docker 公开检查。

```json
{"action":"finish","arguments":{}}
```

`finish` 不会设置通过；只有执行器验证可以产生 `public_checks_passed`。无独立评分时始终 `accepted=false`。

## 错误与恢复

| 错误码 | 意义 | 后续 |
| --- | --- | --- |
| `symbol_not_found` | 没有找到支持的静态声明，不等于运行时名称必定不存在 | 根据有界候选核对名称；不重复猜测动态或通配绑定 |
| `symbol_ambiguous` | 短名匹配多处，或同名静态声明多次出现 | 可用时选择限定名；工具不会执行代码判断分支 |
| `anchor_not_found` | old 在当前文件中出现 0 次 | 必须重新读取该文件 |
| `anchor_ambiguous` | old 出现多次 | 重新读取并选唯一锚点 |
| `anchor_not_supplied` | old 在文件中，但不在已提供片段中 | 必须补读 |
| `stale_source` | 已读哈希与当前文件不一致 | 必须重读当前版本 |
| `read_required` | 前次失败或文件修改后尚未重读 | 读取所列文件，不能直接重发补丁 |
| `source_not_read` | 从未提供该文件证据 | 读取目标符号 |
| `syntax_error`、`no_change`、`invalid_patch_schema` | 暂存检查失败 | 修正申请；已计入编辑尝试 |
| `path_not_allowed` | 越界、不在允许范围或链接路径 | 不可重试，停止任务 |

错误结构包含 `code/message/retryable/next_action` 和适用的文件或候选信息。
测试失败观察与编辑错误分开记录；容器故障、零测试执行和测试超时不作为普通修复反馈反复重试。
预算、响应截断、脚本耗尽等有各自停止状态。未验证通过或发生异常时仍整体回滚，不交付候选。

## 使用

沿用 README 的 D 盘状态/缓存/临时目录配置，先启动 Docker Linux 引擎并确认准备任务的固定镜像。
输出目录必须全新，原管理员配置不可变。

```powershell
# 真实本地推理命令：本次开发没有执行它。
python -B -m repairflow repair-issue --prepared .tmp/github-issues/click-3887 --config configs/issue-tasks/click-3887.json --output .tmp/issue-repairs/recovery-001 --mode ollama --model qwen3.5:27b --workflow symbol-recovery-v1 --max-steps 20 --max-edit-attempts 6
```

脚本模式用 `--mode scripted --responses .tmp/actions.json`，该文件为 1–100 个 JSON 字符串组成的数组。
每个字符串是一份动作或补丁响应。实际执行受上述步数与预算限制，脚本长度不授予额外次数。
演示应明确标注脚本响应，不把执行链路成功计入模型修复率。

## 证据和验收

每步保存 `step-NNN-messages.json`、`step-NNN-response.txt`；适用时保存补丁及 Docker 检查结果。
`actions.json`、`trace.jsonl` 与最终 `report.json` 记录读取结果、结构化错误、编辑次数及终止原因。
轨迹包含可观察动作和结果，不依赖模型内部思考内容；尚无跨进程恢复正在执行动作的保证。

```powershell
python -B -m pytest tests/test_issue_tools.py tests/test_issue_agent.py tests/test_issue_repair.py tests/test_issue_context.py tests/test_github_issue.py tests/test_repair50_evidence.py -q -p no:cacheprovider --basetemp=.tmp/pytest-recovery-review

# Docker 可用后运行，使用本地已构建镜像，不拉取、不调用模型。
$env:CORECODER_RUN_DOCKER_TESTS='1'
python -B -m pytest tests/test_issue_repair_docker.py -q -p no:cacheprovider --basetemp=.tmp/pytest-recovery-docker
```

本轮针对性测试 130 项通过，涵盖第三次编辑成功、重新读取修改后的源码、强制重读、版本/路径/语法、分页、预算及各类停止条件。
第三次编辑成功的[五步验收摘录](symbol-read-recovery-acceptance.json)从实际测试报告提取，明确标注为脚本响应和模拟检查，不是模型或真实容器成绩。
首次交付时流程测试明确模拟容器执行器；当时 3 项真实 Docker 用例因 Linux Engine 管道不可连接而未执行。
最终全量回归 **1739 项通过、18 项跳过，181.03 秒**；Ruff 通过。受限环境首次停在 MCP stdio 测试，核对并结束该测试进程后，在支持本地管道的环境重新执行全量回归通过；未重启已有服务。
不能据此宣称真实容器或真实模型新增修复成功；历史 47/50 不更新。

**后续真实验收（2026-10-23）：**3 项 Docker 用例通过；本地模型复测 6 次调用、0 次编辑，重复查询模块常量/导入名称后停止，仍未修复目标。[结果与下一项缺口](symbol-recovery-20261023.md)。

**模块绑定修复（2026-10-29）：**受限赋值/导入声明读取已实现；全量 1,765 passed、19 skipped，四项真实 Docker 验收通过。本地模型可读取常量并提交三次有效补丁，但正常行为回归未解决，最终预算预检停止并回滚。[完整结果](module-binding-20261029.md)。

**历史观察精简（2026-10-29）：**可选 `compact-v1` 已通过全量 1,782 项回归及 4 项真实 Docker 验收。本地单例通过约定的四项公开检查，Token 53,252 → 24,704，保留待审查补丁，无独立评分。默认仍为 full，不改写历史 47/50。[结果及限制](compact-observations-20261029.md)。
