# 真实仓库 Agent 闭环 v1

## 本次完成

将已准入的 Click 历史缺陷接入 CoreCoder：复制原始仓库，Agent 用受限工具定位与编辑源码、运行公开正常行为检查；结束后，父进程把允许修改的源码放回干净原始仓库，执行目标验收和正常行为检查。

入口为 `python -m evals.real_tasks`。支持 unchanged、reference、scripted、live，报告协议为 `real-agent-loop-development-v1`。原有合成任务入口及默认测试命令保持兼容。

## 输入与评分边界

- 加载准入报告时验证候选清单、目标检查以及原始/修复后源码摘要；每次运行先检查原始缺陷仍能复现，结束后检查上游快照与父进程检查未变。
- 工作区保留完整原始上游仓库与许可证。允许修改整个已有 `src/click/*.py` 范围，不把官方修改文件列表作为定位提示；不允许新增源码文件、修改测试或其他文件。
- Agent 输入包含公开问题描述、统一源码范围、预算和可见测试配置。真实 live 输入不含修复后提交、官方补丁、目标检查或官方修改文件列表。
- `.real-visible/test_admission.py` 只包含 Controls 与共享辅助代码，通过 AST 去除 Target。唯一允许的 shell 命令为 `python -m unittest discover -s .real-visible -v`；工具内部使用准入记录的独立解释器、显式导入候选 src，并只运行 Controls。
- 父进程评分在新建 grading 目录执行，保留原始上游测试，使用父进程独立持有的 Target 与 Controls；修改范围违规直接拒绝。公开 Controls 不是上游完整回归套件。
- reference 与 scripted 使用官方修复进行执行器验收；scripted 的 oracle 数据仅存在于其专用任务文件，不进入 live 输入。

工具限制、工作区复制和独立解释器用于可追溯的开发实验，不构成 OS 沙箱。当前仅支持已人工准入的可信仓库；执行过程中不向模型工具开放父目录，执行测试不继承模型密钥。运行记录和参考材料仅存于忽略的 .tmp，未提交整个上游源码。

## 实测结果

任务 `click-flag-envvar` 的来源和准入见 [真实跨文件准入](real-crossfile-admission-v1.md)。使用 `.tmp/real-defects/crossfile-admission-v2/admission.json` 及其中记录的无第三方依赖 venv 测试解释器。

| 模式 | 目标验收 | Controls | 结果 |
| --- | --- | --- | --- |
| unchanged | 失败 | 通过 | failed_verification，预期 |
| reference | 通过 | 通过 | passed |
| scripted | 通过 | 通过 | passed，含实际工具调用与可见测试 |
| live / keyword | 失败 | 通过 | budget_exceeded，未修改源码 |

2026-10-05，本地 Ollama `qwen3.5:27b`，reasoning_effort none，temperature 0；固定 12 轮、30,000 Token 预算、16,000 上下文估计窗口、单次输出上限 2,048、180 秒 Worker 超时、15 秒单组测试超时；关键词检索默认保留完整历史。

live 共 5 次模型调用，提供方报告输入 25,188、输出 325、合计 25,513 Token；总耗时 23.8932 秒。第 6 次预检估计请求 9,868 Token，加预留输出共 11,916，超过剩余 4,487，因此未发出请求。预算是估计预检结合返回 usage 的限制，不是提供方计费硬上限。

Trace 中先进行了两次 search_code，随后读取 core.py 前 200 行，再执行 grep，没有 edit_file。最后预检中的搜索历史估计为 4,357 Token、read_file 为 2,253；累计输入消耗较高。本次只运行一个开发任务的一种策略，不能据此推断检索效果、模型总体成功率或与其他产品的优劣。

协议验收证据：`.tmp/real-defects/repair-acceptance-v1`；模型证据：`.tmp/real-defects/repair-live-v1/summary-e154bf45b0.md` 及 `click-flag-envvar-d28f0cde0e/report.json`、`trace.jsonl`。源码改动为空，参考修复未进入真实运行。

代码验收：相关测试 19 passed；全量测试 501 passed、1 skipped；修改文件 Ruff 通过。测试覆盖原始失败/参考修复/脚本闭环、live 输入无 oracle、公开检查不含 Target、测试篡改拒绝、可见 shell 命令限制。

## 复跑

在 corecoder 环境、仓库根目录执行；必须先存在对应的成功准入报告与快照。首次建立准入的步骤见真实跨文件文档。

```powershell
python -m pytest tests/test_real_tasks.py tests/test_real_admission.py -q
python -m evals.real_tasks --admission .tmp/real-defects/crossfile-admission-v2/admission.json --mode unchanged --output .tmp/real-defects/repair-acceptance
python -m evals.real_tasks --admission .tmp/real-defects/crossfile-admission-v2/admission.json --mode reference --output .tmp/real-defects/repair-acceptance
python -m evals.real_tasks --admission .tmp/real-defects/crossfile-admission-v2/admission.json --mode scripted --output .tmp/real-defects/repair-acceptance
python -m evals.real_tasks --admission .tmp/real-defects/crossfile-admission-v2/admission.json --mode live --search-backend keyword --output .tmp/real-defects/repair-live
```

每次运行创建新 ID，保留旧结果。unchanged 应退出 1，reference/scripted 应退出 0；live 结果必须由实际评分决定。live 默认本地模型与上述预算，可通过 CLI 参数选择模型、端点和预算；改变预算或协议后须单独标注，不能混入同一对照。开发任务报告始终 benchmark_eligible false。

## 下一步

固定当前真实任务和预算，先分析检索命中位置与重复上下文；把已有搜索历史去重策略接入真实任务入口，与完整历史执行对照，检查能否减少探索阶段 Token 开销并进入编辑。原始失败记录保留，允许无收益。随后扩充任务并冻结开发/留出划分，当前已查看官方修复的案例不进入留出集。
