# P0-1 测试步骤（Windows + conda + Ollama）

后续由用户运行测试，开发者只编写代码、提供命令，并根据返回结果修复问题。以下命令在 PowerShell 中执行；不要求配置远程 API Key。

## 1. 进入环境

```powershell
Set-Location D:\project_other\CoreCoder
conda activate corecoder
python --version
```

预期 Python 3.11.16。若当前终端无法激活 conda，可将下文所有 `python` 替换为：

```powershell
& 'C:\Users\admin\anaconda3\envs\corecoder\python.exe'
```

例如 `& 'C:\Users\admin\anaconda3\envs\corecoder\python.exe' -m pytest tests/test_evals.py -q`。不要使用项目内旧 `.venv`。

## 2. 先验证新增代码，再运行完整回归

```powershell
python -m pytest tests/test_evals.py -q
python -m pytest tests -q
```

当前预期：新增测试 **24 passed**，全部测试 **203 passed**。不调用任何真实模型。

覆盖：5 项缺陷版本失败/参考修复通过/离线工具修复通过；修改测试被拒绝；目标通过但回归失败不能验收；路径越界和任意命令被拒绝；零测试不能验收；超时清理子进程；预算限制；用量缺失；完成声明不计分；密钥脱敏；任务记忆隔离；live 任务不包含参考答案；超时及截断 Trace 保留报告。

可先仅重跑最后新增的测试：

```powershell
python -m pytest tests/test_evals.py -q -k "live_job or partial_trace"
```

预期 **3 passed**。最后一次开发者执行中，live-job 的两个 mock 测试因 Windows 默认 GBK 读取 UTF-8 任务文件而失败；已经显式改为 UTF-8，按用户要求未重跑。其余 201 项通过。此前 200 项版本全部通过；这些结果不能替代当前版本的验证。

可选静态检查（不检查故意带缺陷的 fixture 源码）：

```powershell
python -m ruff check evals/__init__.py evals/__main__.py evals/schema.py evals/process.py evals/runtime.py evals/runner.py evals/worker.py tests/test_evals.py
```

预期 `All checks passed!`。如果没有安装 ruff，可以暂时跳过，不影响评测运行。

## 3. 验证独立评分的负例与正例

```powershell
python -m evals --mode unchanged --output .tmp/evals/user-check
python -m evals --mode reference --output .tmp/evals/user-check
python -m evals --mode scripted --output .tmp/evals/user-check
```

| 模式 | 预期 | PowerShell `$LASTEXITCODE` | 目的 |
| --- | --- | --- | --- |
| unchanged | 5 项 `failed_verification` | 1 | 原始缺陷不能被评分器误判为修复成功 |
| reference | 5 项 `passed` | 0 | 参考修复与独立验收一致 |
| scripted | 5 项 `passed` | 0 | 经真实 Agent 循环、文件工具和可见测试完成参考修复 |

每条命令最后打印汇总 Markdown 路径。reference 和 scripted 明确使用已知参考答案，**不能报告为模型修复成功率**。

## 4. 检查本地模型

```powershell
ollama list
Invoke-RestMethod http://localhost:11434/api/version
```

预期模型列表包含 `qwen3.5:27b`，HTTP 请求返回 Ollama 版本。若连接失败，先启动本机 Ollama 应用/服务；只有确认未运行服务时才使用 `ollama serve`。

本机此前已验证：Ollama 0.34.3、qwen3.5:27b、Q4_K_M、服务端实际上下文 32,768 Token。再次运行可能受服务配置变化影响，以生成报告中的 `ollama_after.loaded.models` 为准。

## 5. 先跑一个真实模型任务

```powershell
python -m evals --mode live --task timeout-units --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --output .tmp/evals/user-live
```

预期正常打印 `timeout-units: passed`，返回码 0。模型修复失败仍是有效结果，不能为获得 passed 修改评分器。若出现 `agent_error`，检查 `worker-result.json` / `worker.stderr.txt`；`timeout` 检查 Trace 最后完成的调用；`budget_exceeded` 检查预算字段。

默认轮次 12、Token 预算 30,000、单次输出 2,048、Worker 时间 180 秒、每组测试 15 秒。首先保留默认配置。确需调整时保存新结果，不覆盖原有失败，后续策略比较使用相同参数。

## 6. 跑完整 5 项样例

```powershell
python -m evals --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --output .tmp/evals/user-live
```

每项从全新工作区开始，预期生成 5 份报告和 1 份汇总。此前开发过程中的一次真实模型试跑为 5/5 通过，尚不是当前最终版本的固定基线。最后启动的额外确认试跑已按用户要求停止，其未完成目录不用于汇总结论。

需要冻结基线并确认重复性时，再主动执行：

```powershell
python -m evals --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --repeat 3 --output .tmp/evals/user-baseline
```

这会运行 15 次真实模型任务，耗时较长；在前面步骤通过后再做。人工任务规模小、描述明确，结果只证明闭环可运行，不能据此声称改善仓库级修复成功率。

## 7. 检查报告与反馈

终端末行即本次汇总路径。打开相应 `summary-*.md` 与 JSON，检查每项 `status`、`accepted`、`verification.target.passed`、`verification.regression.passed`、`scope_violations`、Token、耗时与配置。

每个任务目录保留 `patch.diff`、目标/回归测试输出、Trace、候选代码、独立验证代码和版本哈希。检查补丁确实改变源码、没有改测试。未知 Token/费用应为 null，不应当成 0。真实模式 `job.json` 不包含 `oracle_edits` 或目标测试。

向开发者反馈：失败的完整 pytest 输出，或任务状态、汇总路径及对应 `report.json` 的非敏感错误内容即可。不要提供 API Key。完成这组验收后，再进入检索与上下文策略开发。
