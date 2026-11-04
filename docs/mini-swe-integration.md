# mini-SWE-agent 接入与本地对照

后续 [Click 单项预算诊断](mini-swe-budget-20261103.md)：只调累计预算到 100k 后，生成候选并通过目标 2/2、正常行为 2/2；16 次调用、90,624 Token，仍因预算停止而未主动提交。该结果不覆盖下方原五项 0/5，且两轮目录枚举顺序不同，不能作确定性因果结论。

## 目的与当前结论

把成熟 Agent 接入现有模型、沙箱、独立评分和 Langfuse，判断失败是否能通过更换执行循环改善。
这是可运行的**可选评测入口**，未替换原 CLI、Issue API 或审批流程；目前只接受预先固定的 5 项旧开发任务。

2026-11-03 本地单轮结果：冻结的旧 v1 循环 **0/5**，mini-SWE-agent **0/5**。本轮 **36 次真实调用、126,472 Token**，没有修改原有源码；同子集旧 v1 为 112,443 Token。
五条 Trace 的 Generation 数量和原生 Token 均已回读核对，评分在 Agent 终止后独立执行。
结果不支持直接替换现有核心，也不能推出其他模型、预算或 mini-SWE-agent 配置同样无效。

| 开发任务 | 独立验收 | 调用 | 实测 Token | 停止原因 |
| --- | --- | ---: | ---: | --- |
| click-usage-empty | 未通过 | 7 | 22,135 | 累计预算预检查 |
| toolz-join-unmatched | 未通过 | 6 | 24,830 | 累计预算预检查 |
| boltons-repeat-equality | 未通过 | 6 | 23,531 | 累计预算预检查 |
| toolz-merge-mapping | 未通过 | 7 | 28,453 | 累计预算预检查 |
| more-reverse-empty-range | 未通过 | 10 | 27,523 | 累计预算预检查 |

共执行 36 条有效 Bash 动作；35 条为定位/读取，1 条创建并运行临时复现脚本。没有格式解析失败、模型响应截断或命令超时；4 次较大的命令输出由上游模板裁剪为首尾片段，并向模型标记省略。
例如 Click 已读到目标函数，仍继续读取调用方和测试；Toolz 能按搜索行号读取 `join`，没有旧工具的字符偏移混淆，但尚未编辑就停止。
完整消息历史持续累积；当剩余预算不足以发送下一次输入并预留输出时停止，所以实际消耗可能低于 30,000。
这是当前预算与行动分配不匹配的证据，尚未通过消融证明缩短历史、增加预算或更换模型各自能带来多少收益。

之前可选 checkpoint 策略的 2/3 仍是另一份三项开发实验，未被这轮覆盖；历史 DeepSeek 47/50 也保持原协议。不要把三组数字当作同一配置的连续变化。

## 接入边界

```text
原公开缺陷 + 导出基线
  → mini-SWE-agent 2.4.6 DefaultAgent（未改循环）
  → 本地 Ollama 文本模型适配器（think=false）
  → 上游 Bash 动作解析 → 受限 Docker 执行 → 观察写回原版线性历史
  → 停止后导出补丁 → 原 Target/Controls 独立评分 → Langfuse 分数与用量核对
```

- **复用上游：**DefaultAgent、默认提示模板、文本动作解析、观察格式、格式错误恢复及轨迹保存。
- **新增适配：**本地 Ollama 原生文本 API、实际用量记账、执行预算、受限 Docker Environment、补丁导出与旧评分器连接。
- **明确差异：**使用上游仍支持的文本 Bash 协议；上游 v2 推荐原生 Tool Calling，本入口尚未接入。工具、提示、历史与编辑次数约束都不同，因此是完整流程比较，不是单因素消融，也不代表上游榜单配置。
- **模型固定：**`qwen3.5:27b`、相同 digest、temperature=0、think=false；最多 20 次请求、累计 30k Token、单次输出最多 2048、估算请求上下文上限 16k、任务 1200 秒。
- **独立验收：**复用旧 50 项的未修改/参考补丁控制记录、固定镜像及手写 Target/Controls；不是完整上游测试，也不是 SWE-bench 分数。隐藏检查和参考修复不进入模型或执行容器。
- **修改范围：**仅允许原有约定源码进入评分；修改原测试/配置或删除基线文件会失败。新建复现助手留作制品，不提交评分，故本入口暂不支持新增源码文件型任务。

容器禁网、非 root、只读根文件系统，删除 capabilities，限制 1 CPU/1 GiB/64 PID；命令最多 30 秒、输出最多 1 MiB。
只读挂载导出基线 `/seed`，工作区使用 tmpfs；不挂载宿主可写目录、评分材料、密钥或 Docker socket。Bash 始终在容器内执行。
结束导出有界文本快照后删除该任务容器。此配置复用现有小镜像，不提供 Git、联网或安装依赖能力，不能冒充完整上游环境。

## 在 D 盘安装与运行

要求现有 `corecoder` Python **3.11+** 环境、Ollama 模型和 `corecoder-test-sandbox:v1` 已可用，且 `.tmp/local50-chain-20261103` 的基线及任务素材完整。
此开发对照还需要已部署的本地 Langfuse；没有付费 API Key 也能运行。

```powershell
conda activate corecoder
cd D:\project_other\CoreCoder
$env:TEMP="$PWD\.tmp"; $env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHON_DOTENV_DISABLED='1'
$env:CORECODER_HOME="$PWD\.tmp\mini-swe-state"
$env:MSWEA_GLOBAL_CONFIG_DIR=$env:CORECODER_HOME
$env:MSWEA_SILENT_STARTUP='1'
$env:NO_PROXY='127.0.0.1,localhost,::1'

# 仅安装本入口需要的 Python API 子集，不安装上游完整 CLI 或 LiteLLM 后端。
# 先确认原环境已有 pydantic>=2、PyYAML、rich、python-dotenv。
python -B -m pip install --target .tmp/mini-swe-deps --no-deps --no-cache-dir --no-compile -r deploy/mini-swe-api-requirements.txt
$env:PYTHONPATH="$PWD\.tmp\mini-swe-deps;$PWD\.tmp\langfuse-deps;$PWD"
$env:CORECODER_LANGFUSE_ENABLED='1'
$env:CORECODER_LANGFUSE_ENV_FILE="$PWD\.tmp\langfuse-local\.env"
$env:CORECODER_TEST_BACKEND='docker'

# 使用新目录；不自动重试或覆盖已有推理。
python -B -m evals.mini_swe --output .tmp/mini-swe-my-pilot
# 单项开发检查可加 --task click-usage-empty
# 仅显式诊断时加 --token-budget 100000；默认仍为 30000。
```

验证接入代码（默认不调用模型和 Docker）：

```powershell
python -B -m pytest tests/test_mini_swe.py -q
# 显式启用真实 Docker 烟测，仍不调用模型、不拉取镜像：
$env:CORECODER_MINI_DOCKER_TEST='1'
python -B -m pytest tests/test_mini_swe.py -q
```

本轮 8 项接入测试通过，含一次实际上游循环修改、容器导出及宿主基线不变验证；相关回归 83 项通过、1 项真实 Docker 用例默认跳过（该用例另行实跑通过）。
测试覆盖文本请求禁用 thinking、失败响应用量、格式恢复和历史传递、容器边界、命令超时退出、删除拒绝及 API Key 不传入子进程。

## 产物与后续

运行目录 `.tmp/mini-swe-pilot-20261103` 保存协议、模型身份、逐任务请求/响应、Bash 输出、上游 trajectory、补丁和独立评分；`langfuse.json` 保存真实推理节点及用量回执。
离线证据见 [mini-swe-20261103.json](mini-swe-20261103.json) 与 `mini_swe_20261103/`；不包含凭据和整份仓库副本。

不自动扩大到 50 项、不接入付费模型，也不把此入口称为生产替代品。若继续优化，优先在少量固定任务上检验**历史长度和定位/编辑预算分配**，再决定是否接入 v2 原生 Tool Calling；每次只改变明确因素，保留失败记录。

参考：[上游代码与许可证](https://github.com/SWE-agent/mini-swe-agent)、[本地模型说明](https://mini-swe-agent.com/latest/models/local_models/)、[官方评测用法](https://mini-swe-agent.com/latest/usage/swebench/)。
