# P0-1：任务与独立验证闭环

当前实现包括独立修复验证闭环、关键词证据工具、可选上下文/提示实验、固定公开证据补丁诊断和有界修复管线，尚未开发向量检索或服务端。复用上游 CoreCoder 的 Agent 循环、文件工具、LLM 接口与上下文压缩；新增任务协议、受限工具适配、独立 Worker、预算、验证器和证据记录。

P0-2 新增的 5 项人工开发任务独立放在 `fixtures/localization-v1/`，需要显式传入 `--suite evals/fixtures/localization-v1`，默认命令仍运行原来的 5 项回归任务。设计和验收步骤见 [开发任务说明](../docs/p0-2-localization-tasks.md)。任务已完成用户离线验收，历史真实模型结果单独保留。

`--search-backend off|none|keyword` 可选择不添加搜索工具、空证据控制或关键词证据。off 为兼容默认；none/keyword 使用相同 Schema 和提示。实现、限制及用户验收命令见 [search_code 说明](../docs/p0-2-search-code.md)，已执行的对照见 [实验结果](../docs/search-code-v1-results.md)。

## 快速运行

在项目根目录使用已安装的 conda 环境，无需新增依赖：

```powershell
conda run -n corecoder python -m evals --mode unchanged
conda run -n corecoder python -m evals --mode reference
conda run -n corecoder python -m evals --mode scripted
conda run -n corecoder python -m evals --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none
conda run -n corecoder python -m pytest
```

`unchanged` 预期 5 项全部失败，退出码为 1；`reference` 与 `scripted` 预期全部通过，退出码为 0。这三种模式不调用模型。`live` 是 Agent 模型执行；`pipeline` 是有界检索与单请求修复；`fixed-evidence` 为单请求补丁诊断，不计 Agent 基准。存在未通过任务时退出码为 1，取消返回 130。

可用 `--task timeout-units` 选择单项，重复 `--task` 选择多项，`--repeat 3` 从干净工作区重复运行。`--output .tmp/evals/my-run` 指定产物位置，每次运行使用独立目录。模型别名、量化、实际上下文长度和运行日期需要一起保存；Ollama 元数据记录在报告中。`--context-tokens` 是评测侧估算限制，不会修改 Ollama 服务端窗口。

远程模型需显式设置 `--model` 和 `--base-url`，在本地 `.env` 配置 `CORECODER_API_KEY`、`DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`；本地 Ollama 无需密钥。当前 CLI 默认远程模型名仅为可覆盖配置，未验证其服务可用性，首次运行请使用上面的 Ollama 命令。

## 任务与验收

| 任务 | 缺陷 | 跨模块调用链 |
| --- | --- | --- |
| timeout-units | 秒到毫秒转换错误 | settings → transport → service |
| tenant-cache | 不同租户的缓存键冲突 | keys → store → service |
| retry-policy | 不应重试的响应被重试 | policy → worker → service |
| inclusive-date | 结束日期遗漏 | date_utils → window → service |
| falsey-overrides | 0 / False / 空字符串配置丢失 | defaults → options → service |

这些是小型人工缺陷，每项含 3 个源码模块，修复通常只需改 1 个文件。其描述较明确、难度低，不能代表真实仓库检索难度或最终任务分布。

每项目录包含 `task.json`、`workspace/`、`hidden_tests/` 与 `reference.json`。任务及运行预算由冻结的 dataclass 校验；工具参数保持上游 JSON Schema。

1. 父进程复制缺陷版本到独立工作区。
2. `live` Worker 只接收缺陷描述、允许修改的文件、配置和工作区路径，不接收参考修复或目标测试；`scripted` 明确接收参考修复，专用于测试工具链。
3. Agent 完成或到达预算/超时后，父进程检查全部文件变化，保存补丁，拒绝修改测试、越界文件、删除允许文件及符号链接。
4. 在全新的验证目录中，父进程从原始版本复制可见测试，再覆盖允许的候选源码，最后加入评测侧目标测试。目标与回归测试分别运行。
5. 只有正常完成、范围检查通过、目标及回归测试均通过且确实发现测试，才记为成功。模型的完成声明不能改变评分。

## 固定的执行条件

初始受限基线使用 read_file / glob / grep / edit_file / write_file / todo_write / bash。每个任务创建新工具实例、新 Agent 和独立进程；批量工具调用按响应中的顺序执行，避免并行读写竞态，任务列表继续注入上下文。没有启用子 Agent、MCP 或任意命令执行。

`bash` 仅接受 `python -m unittest discover -s tests -v`，实际使用当前 conda 解释器执行。源码只允许写入 manifest 指定的文件。测试环境不继承模型凭据及 Python 启动钩子。**这是受限的 CoreCoder 基线，与原版不限命令、并行工具调用的运行方式不同**；后续检索对照在同一执行条件下进行。

默认参数：temperature=0、12 轮、估算上下文 16,000 Token、单次输出上限 2,048 Token、任务 Token 预算 30,000、Worker 墙钟 180 秒、每组测试 15 秒。墙钟限制不含父进程准备和独立验收；端到端耗时另列。Token 预检使用估算并预留输出，返回 usage 超限后停止后续工具执行；它不是提供商账单的绝对上限。超时终止 Worker 进程树，保留已有 Trace 与报告。

## 产物与指标

每次运行保存：

```text
<task>-<repeat>-<unique-id>/
  report.json                # 配置、状态、版本/哈希、用量、验收与耗时
  trace.jsonl                # 模型调用、工具参数/结果、耗时与错误
  patch.diff                 # 实际工作区变化
  job.json                   # live 中无参考修复和目标测试
  worker-result.json         # 模型最终回答、Prompt/Schema 哈希、Ollama 信息
  worker.stdout/stderr.txt
  target.stdout/stderr.txt
  regression.stdout/stderr.txt
  workspace/                 # 候选代码
  grading/                   # 父进程生成的独立验收目录
summary-<unique-id>.json/md
```

模型用量按全部实际完成的调用累计，包含 CoreCoder 上下文压缩请求。缺失 usage 记为 `null`，同时记录估算预算和已知部分；失败提供商尝试的用量未知，费用未核算，不能当作 0。硬超时可能没有 `worker-result.json`，此时用量记为未知，已经完成的调用仍可在 Trace 中查看。Trace 不保存模型内部推理，环境中的常见密钥值被脱敏。

报告记录源码哈希、Git 基点/状态、依赖版本、任务/目标测试哈希；Worker 保存 Prompt 与工具 Schema 哈希。工作区产物默认在已忽略的 `.tmp/`，共享报告前仍应检查其中的数据。保留所有失败，不能只保留成功记录。

## 当前边界与下一步

`python -m evals.retrieval_eval` 离线评测默认 11 个任务的文件级种子 Recall@K、MRR、无预算静态依赖闭包与实际限额证据覆盖，不调用模型。默认 K=1/3/5/10；`--suite` 可重复指定套件，`--dependency-depth` / `--max-chars` 控制依赖和证据预算。标签来自参考修改文件，仅供评分，不进入索引或查询；完整口径、44 份观察与复跑见 [retrieval-quality-v1](../docs/retrieval-quality-v1.md)。

`--mode pipeline --search-backend keyword` 按缺陷描述检索，再沿静态依赖构建完整文件证据，单次生成 JSON 补丁并独立验收。`--evidence-top-k` 默认 5、`--evidence-dependency-depth` 默认 2，正文上限由 `--search-max-chars` 设置（默认 6,000）。仅允许默认 baseline 提示、context-policy=none、search-history=full；协议标为 bounded-pipeline-v1，同协议可做策略对照，与旧 Agent 混合汇总不标为共同基准。六次 pilot、实现边界和复跑命令见 [bounded-pipeline-v1](../docs/bounded-pipeline-v1.md)。

管线的 `--evidence-order selection|path` 在预算裁剪后保留选择顺序或按路径排序，文件内容及集合不变。Trace 保存顺序无关证据哈希与实际请求顺序；实现、交错复跑及结果见 [evidence-order-v1](../docs/evidence-order-v1.md)。

pipeline_evidence_built 另记录 ranked_chunks、candidate_files、seed_count，区别请求 K、正分候选与实际种子数量；增加 K 不保证扩大证据集合。K5/K10 的干预检查与六次租约对照见 [evidence-width-v1](../docs/evidence-width-v1.md)。

`--mode fixed-evidence` 一次性提供允许源码与公开契约，无工具循环，请求 JSON 补丁并使用同一独立验证器。报告 benchmark_eligible=false；不可混用 Agent 策略，不能与 Agent 或 RAG 策略直接归因比较。模式、边界、六次运行与换行重放见 [fixed-evidence-v1](../docs/fixed-evidence-v1.md)。

修复提示支持 `--prompt-policy baseline|contract-check`，默认 baseline 保持原文；检查组追加通用症状/契约/验证覆盖要求，属于单独 Prompt 干预，尚无可靠收益。实现与 pilot 见 [contract-check-v1](../docs/contract-check-v1.md)。

上下文实验支持 `--context-policy none|read-cover`（默认 none；read-cover 要求 keyword 与 search-history=full）。完整读取在同版本、同路径且保留在历史时，可在下一轮请求视图中覆盖旧搜索正文，原历史保留；详见 [read-cover-v1](../docs/read-cover-v1.md)。Trace 追加每轮角色/工具消息估算、Schema 估算、剩余预算及阻断原因；估算与实际 usage 分开解释。

本版适用于自行审查过的人工任务。路径约束和独立评分不等于操作系统沙箱：测试会在宿主机运行候选 Python，恶意代码仍可能访问其他宿主资源；目标测试在验证阶段才加入工作区，但没有针对恶意代码建立保密边界。引入外部历史仓库前需增加容器隔离，再做完整的环境和数据纳入检查。

先冻结任务与执行配置、扩展更有跨文件理解需求的开发任务，再接入同 Schema 的 `search_code`，比较关键词/向量/混合检索以及上下文组织。人工任务用于机制调试，公开历史缺陷与留出集用于最终结论，分别报告。
