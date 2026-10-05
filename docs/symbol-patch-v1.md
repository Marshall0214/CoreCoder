# 局部上下文结构化补丁：开发协议 v1

## 实现

新增 `evals/symbol_patch.py`，将已验证的局部证据接入一次 JSON 补丁请求。固定符号索引、公开标识符查询、依赖预留装填和完整种子依赖分析；CLI 默认 6,000 字符、5 个种子、依赖深度 1。模型收到原始问题描述和片段正文、路径、行号、完整性、符号范围及完整文件版本。

模型无工具调用，无额外读取或修改整个仓库的能力；只能返回 edits。`apply_symbol_patch` 检查 old 文本实际已展示，再校验允许路径、源码版本和唯一匹配，全部校验后写入。空证据不调用模型；空 edits 不等于修复成功；无效补丁保留输出并报告 invalid_patch。

`evals.real_tasks --workflow symbol-patch --mode live` 使用独立子进程运行补丁阶段。父进程沿用原准入预检、允许范围、源码与验收摘要保护，将允许源码改动复制到原始源码的新副本，再运行 Target 与 Controls。工作进程不接收官方修复路径、修复后源码或 Target；验收结果不回传模型。

这是单请求补丁协议 `symbol-patch-development-v1`，不是原 Agent 工具循环协议。不能将两者成绩直接相减解释成检索收益；仍为 development-only，benchmark_eligible false。Worker 的 completed 仅表示补丁协议完成，accepted 必须由独立验证决定。允许范围为整个 src/click，不从官方修改列表取范围。

## 一次真实模型 pilot

使用 Ollama qwen3.5:27b / Q4_K_M，temperature 0、reasoning_effort none，最大输出 2,048 Token、上下文预算 16,000 Token、总 Token 预算 30,000、墙钟上限 180 秒。任务为已知开发案例 click-flag-envvar。

| 项目 | 实测 |
| --- | --- |
| 证据正文 | 5,764 字符，含完整 BoolParamType 与两个关键取值方法 |
| 模型调用 | 1 次，无工具调用 |
| Prompt / Completion Token | 3,255 / 412，总计 3,667 |
| 模型调用耗时 / 总耗时 | 16.7781 / 20.0287 秒 |
| 补丁 | 修改 core.py，范围校验通过 |
| 公开 Controls | 3 项通过，仅该组回归，不是完整上游测试 |
| 隐藏 Target | 失败，无超时或执行错误 |
| 最终 | failed_verification，accepted false |

模型在 Option.resolve_envvar_value 中用 `self.type.convert(rv, self, ctx)` 的真假值判断激活。非布尔参数的转换结果仍可能是非空字符串，所以假值或不匹配值仍会触发开关。它也未修改 types.py 的布尔空白值转换逻辑。

以上是父进程验收后的开发者分析，未作为第二次请求反馈。本次没有重试或用参考补丁替换模型结果。说明：取回相关源码并成功落地合法补丁，仍不保证语义正确；单个已知案例的一次 pilot 不能作为总体成功率或优于原工具循环的证据。

## 测试与复现

新增测试覆盖一次请求、局部元数据、CRLF、无效 JSON、未展示文本/越界拒绝、模型调用期间版本变化、工具调用拒绝、空证据/空补丁，以及在新副本独立评分的确定性验收。确定性验收是测试桩，不计模型成功。

证据目录：`.tmp/real-defects/symbol-patch-v1-pilot/click-flag-envvar-24e7dcb8c6/`，包含 report.json、job.json、trace.jsonl、symbol-patch-response.txt、patch.diff 和独立 grading-logs。实现摘要：`81c1118ca86f2b3a3c1561f73c5595ed3fd479eae86ae489c64252b79fd1efdf`。

```powershell
python -m pytest tests/test_symbol_patch.py tests/test_real_tasks.py -q
python -m evals.real_tasks --admission .tmp/real-defects/crossfile-admission-v2/admission.json --mode live --workflow symbol-patch --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --evidence-dependency-depth 1 --output .tmp/real-defects/symbol-patch-reproduction
python -m pytest tests -q
```

Ollama、对应模型、准入报告和源码须已存在。每次创建独立运行目录；未通过验收的 CLI 返回 1 是正确行为，具体原因查看 report.json。全量回归 534 passed、1 skipped；本次相关文件 Ruff 通过。

## 下一步

后续公开行为核对 Prompt 对照已完成，见 [symbol-prompts-v1.md](symbol-prompts-v1.md)：两组均 0/3，通过核对指令未取得最终修复收益，保持原默认策略。

基于原始公开问题描述增加明确的行为检查清单，在一次请求内要求模型核对“激活判定”和“参数转换”、空白布尔值及不匹配环境变量。将其作为独立 Prompt 策略与当前 baseline 比较；不提供隐藏测试、参考实现或正确补丁。先完成协议测试，再做小规模重复 pilot，保留每次失败，不把改写 Prompt 后的结果合并进本次记录。
