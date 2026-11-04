# 自有 Agent：本地无 Token 截止的 50 项评测

## 本轮目的与协议

检查在取消人为 Token 截止后，自有仓库级修复流程在原 50 项任务上的实际效果；不是 mini-SWE-agent 实验，也不复用历史 DeepSeek 补丁。

- **Agent：**已有 `repository-checkpoint-v1`，搜索/读取 → 完整符号 → 候选补丁。沿用读取记录、唯一锚点、语法和范围校验；首次有效候选后结束，评分在另一阶段执行，无隐藏测试反馈或自动模型重试。
- **模型：**已安装的 Ollama `qwen3.5:27b`，think=false、temperature=0，记录实际 digest。
- **取消限制：**累计 Token 预算为 `null`；Ollama `num_predict=-1`，不再配置 2048 的输出上限；取消额外 16k 请求预检查。原生输入/输出 Token 仍逐次记录，缺失用量不当作零。
- **保留边界：**每项最多 20 轮、1200 秒、最多 6 次编辑尝试、3 次重复动作/连续错误保护、候选阶段最多 2 次依赖补读。模型实际上下文设置仍为 65,536；时间、内存和模型容量并不会无限。
- **测试：**原 5 个仓库、50 项已知开发任务；全部重新运行未修改/参考修复控制组，运行一次脚本编辑与独立评分烟测，再逐项真实生成与后置 Target/Controls 验收。
- **环境：**沿用已有禁网小型 Docker 评分镜像；搜索读取和受约束文本补丁不执行生成代码，测试在受限容器中执行。新增依赖、数据与缓存均在 D 盘，无付费 API。

原有字符级读取/证据大小约束、工具能力和候选策略不随本轮改变。这里的“无 Token 截止”指不再因累计数或人为输出数停止，不等于无限上下文或无限执行。
`num_predict=-1` 的含义可核对 [Ollama 官方参数说明](https://docs.ollama.com/modelfile#valid-parameters-and-values)。

本轮同时使用已有 checkpoint 策略并解除 Token 限制，与旧 v1 的完整 0/50 不能作单因素因果比较；之前 checkpoint 的 2/3 仅来自三项开发试验。历史 DeepSeek 47/50 另有模型及评分协议，不与本轮拼接。

## 运行与恢复

```powershell
conda activate corecoder
cd D:\project_other\CoreCoder
$env:PYTHONPATH="$PWD\.tmp\langfuse-deps;$PWD"
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHON_DOTENV_DISABLED='1'
$env:PYTHONIOENCODING='utf-8'
$env:CORECODER_HOME="$PWD\.tmp\unmetered-state"
$env:TEMP="$PWD\.tmp"; $env:TMP=$env:TEMP
$env:NO_PROXY='127.0.0.1,localhost,::1'
$env:CORECODER_LANGFUSE_ENABLED='1'
$env:CORECODER_LANGFUSE_ENV_FILE="$PWD\.tmp\langfuse-local\.env"
$env:CORECODER_TEST_BACKEND='docker'

python -B -m evals.local50_unmetered --output .tmp/local50-unmetered-my-run
# 原目录中断后恢复；已完成推理或已标记错误的任务不自动重试：
python -B -m evals.local50_unmetered --output .tmp/local50-unmetered-my-run --resume
```

入口独立于旧 `evals.local50`，旧实现及证据不改写。每轮冻结源码、任务清单、模型身份和镜像；恢复时检查哈希与批次锁，不混入修改后的实验代码。
取消 Token 截止的适配器只接受固定本地 Ollama 配置，不能直接用于付费模型。

## 结果状态

正式推理目录：`.tmp/local50-unmetered-checkpoint-20261103-v2`。**50 项全部完成，独立验收通过 21/50（42%），33 项生成有效候选。**
全部 50 项控制组通过，正式批次基础设施异常为 0；真实模型请求 309 次，输入输出合计 **937,866 Token**，未知用量任务为 0。
本轮 Token 截止事件为 **0**。相关条件下的单轮已知开发集结果，不代表陌生 Issue 或官方 SWE-bench 成绩。

| 仓库 | 任务 | 生成补丁 | 独立验收通过 |
| --- | ---: | ---: | ---: |
| Click | 10 | 4 | 2 |
| ItsDangerous | 3 | 1 | 1 |
| Toolz | 6 | 5 | 5 |
| Boltons | 7 | 2 | 2 |
| More-itertools | 24 | 21 | 11 |
| 合计 | 50 | 33 | 21 |

剩余 29 项分为：

- **未生成补丁 17 项：**16 项重复动作停止，1 项连续工具错误停止。
- **补丁未通过验收 12 项：**11 项目标测试未过但正常行为检查通过；1 项目标与正常行为检查均未过。

7 项累计用量超过旧 30k 阈值，最高 82,411 Token，**这 7 项仍全部失败**。本轮没有响应超过旧 2048 输出数，最大请求估算为 8,150，未触及旧 16k 上限。
这些数据说明不能将 21 项成功归因于解除 Token 限制；预算放宽允许任务继续，但剩余问题主要落在行动推进与候选正确性。当前结果也混合了已有 checkpoint 策略，尚无其完整 50 项、30k 条件的同框架对照，不作单因素提升结论。

Langfuse 数据集 50 项、真实推理 Trace 50 条均已回读验证，共 309 个 Generation，用量合计与本地完全一致；发布阶段额外模型调用为 0。
[查看本轮实验](http://127.0.0.1:3300/project/corecoder-issues/experiments/results?baseline=38897f3eb71e229e)。
冻结证据见 [清单与哈希](local50-unmetered-20261103.json)、[逐项 CSV](local50_unmetered_20261103/tasks.csv)；原始请求、响应和 Trace 保存在本轮 D 盘目录。

相关离线回归 **64 项通过**，覆盖超过旧累计/上下文阈值后仍执行、原生失败用量保留、未知用量、无限预测参数、checkpoint 修复链路及批处理路由。

首目录 `.tmp/local50-unmetered-checkpoint-20261103` 已完成全部 50 项控制组及脚本烟测，但控制器适配遗漏 `subprocess.STDOUT`，导致模型进程均未启动（真实调用 0）。修复并补测后使用新目录；仅复用已通过且源码清单、模型及镜像身份一致的 100 份控制组记录和脚本烟测，不复用任何候选或推理。复用来源与哈希写入 `control-reuse.json` 并关联新协议。首轮属于基础设施故障，不能计作 0/50 模型修复成绩。
