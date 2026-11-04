# 使用旧 50 项任务检查当前 Agent 链路

本轮使用历史 5 个仓库的 50 项任务，验证当前仓库 Agent 的执行链路，不运行 SWE-bench Mini，不下载新镜像，也不复现旧 DeepSeek 94% 成绩。

## 验证范围

```text
固定旧任务及源码 → 全部未修改/参考控制组 → 脚本编辑烟测
    → Qwen 搜索/读取/编辑循环 → 保存候选 → 独立 Docker 评分
    → 保存补丁/Trace/实测 Token → Langfuse 数据集实验及服务器回读
```

- 数据源：`docs/repair50_evidence/inputs/manifest.json`；实际源码和评分文件在既有 `.tmp/real-defects` 中，启动前校验 before、after 和 checks 的原哈希。
- 50 项组成：Click 10、ItsDangerous 3、Toolz 6、Boltons 7、More-itertools 24；均为已知开发任务，不是新的留出测试集。
- Agent 复用 `evals.swebench_agent.RepositoryTools`、`explore`、`AgentTelemetry` 和既有 Ollama/BudgetLLM，没有切回历史“自动选好代码后一次生成”的修复流程。
- 每项模型仅接收原问题描述、仓库、源码身份以及自己读取的原始仓库文本。参考版本和独立 Target/Controls 不进入 Worker 请求，原始仓库自带测试可读。基线身份是源码 SHA-256，标记为 `source-sha256:`，不伪装成 Git commit。
- Qwen3.5:27b、think=false、temperature=0；20 步、6 次编辑、30,000 Token、2,048 单次输出、估算上下文 16,000、deadline 1,200 秒。没有隐藏测试反馈或自动模型重试。
- 评分复用既有 `corecoder-test-sandbox:v1`：禁网、非 root、只读源码/评分器、CPU/内存/进程/超时/输出限制；不执行宿主机候选代码。

## 分清工程验证与模型效果

1. **控制组：**全部 50 项先验证原始 Target 失败、Controls 通过；仅覆盖允许源文件的参考修复应使二者均通过。任一环境不满足，停止预检，不开始真实模型推理。
2. **脚本烟测：**使用参考修复生成固定 JSON 动作，真实经过 read_file、唯一锚点 apply_patch、finish、沙箱 Target/Controls。只证明补丁与验证链路可运行，不计算为模型成功或真实 Token。
3. **真实模型：**逐项自主搜索、读取、编辑，停止后独立评分。重复读取、预算耗尽或空补丁均保留；正确性由测试决定，不由模型 finish 决定。
4. **观测验收：**50 项导入一个 Langfuse Dataset/Experiment，真实推理 Trace 保留原生 Token；结果导入不再次调用模型、不复制 GENERATION。回读核对数据项、评分及原始推理节点/用量。

本轮成功指标仅是既有手写 **Target + Controls** 通过及修改范围合法，不等于上游全套测试，也不等于旧实验包含公开检查/冻结检查/回滚在内的 accepted 协议。结果不与历史 47/50 直接比较，更不记作官方 SWE-bench 成绩。

候选导致的测试执行失败与 Docker 创建/控制失败分别保留，无法取得可信测试计数时不算通过。API、审批、SSE 和重启恢复不属于本轮复测范围。

## 运行与产物

```powershell
$env:PYTHONPATH='D:\project_other\CoreCoder\.tmp\langfuse-deps;D:\project_other\CoreCoder'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
python -B -m evals.local50 --output .tmp/local50-chain-20261103
# 中断后恢复，已评分或已终结的任务不重新请求模型：
python -B -m evals.local50 --output .tmp/local50-chain-20261103 --resume
```

目录内 protocol.json 固定任务与实现，identity.json 固定模型 digest 和现有沙箱镜像 ID，report.json 记录预检与逐任务进度。每项包含 public.json、控制组、agent/patch.diff、actions.json、trace.jsonl、原始用量和 grading/report.json；langfuse.json 保存最终服务器回读。

2026-11-03，新增代码与既有相关测试 **63 项通过**、Ruff 通过。独立真实 Docker 脚本烟测 `toolz-join-unmatched` 已完成：读取、修改 `toolz/itertoolz.py` 后 Target/Controls 通过，真实模型调用 0。现场产物在 `.tmp/local50-scripted-smoke-20261103`。批次最终成绩以新的 report.json 为准，未完成前不报告 50 项成功率。

**同日全量环境预检已完成：50/50 项全部满足控制组条件。**共执行 50 项 × 未修改/参考两组 × Target/Controls 两类检查。批次内再次执行的脚本编辑烟测也通过；随后自动开始 50 项本地模型真实修复。环境预检与脚本烟测不计入模型修复成功数，真实模型运行结果仍以 `.tmp/local50-chain-20261103/report.json` 为准。

首个真实模型任务 `click-usage-empty` 因预算保护停止，空补丁，独立 Target/Controls 判定未修复。服务器回读核对了其 [Langfuse Trace](http://127.0.0.1:3300/project/corecoder-issues/traces/c8ba770161cc8a5db8ab60e36245f4fe)：7 个 GENERATION、输入 24,125 + 输出 170 = 24,295 Token，节点均结束，与本地报告一致。回执为批次目录 `first-trace-receipt.json`；此项只确认推理、失败评分和用量上报接通，不表示修复成功。

**本轮最终完成：**50 项全部独立评分、0 环境异常、0 非空补丁、通过 0/50；371 次调用、1,193,835 Token。停止原因为预算 27、重复动作 21、连续工具错误 2；Langfuse 50 项实验结果和 50 条原始推理轨迹均回读确认。随后的[候选生成开发试验](repository-checkpoint-20261103.md)独立记录，不改写这轮结果。
