# 反馈上下文与动作合同

状态（2026-11-09）：P3 接口实现、离线验证、录制容器回放与本地短请求兼容验证完成。后续[五项真实 Issue 验收](feedback-pilot-20261109.md)已另行归档；本篇保留 P3 的结果口径，服务端输入完整性仍待证明。

## 改了什么，为什么

上一阶段已让模型在失败后重新读取、编辑并测试。本轮处理两个接口问题：只要求 JSON 仍可能收到错字段；按需读取之后，也需要明确知道每轮实际送入了哪些代码。

| 能力 | 实现与边界 |
| --- | --- |
| 动作 Schema | 六种动作各有独立字段合同；读取 offset、工作区 revision 必须为非负整数，补丁为 1–20 个 edit，拒绝额外字段、空锚点、重复 JSON 键和非有限数。Schema 与执行前检查共用一份规则。 |
| 生成约束 | 显式向本地 Ollama 的 `format` 传入 Schema，同时放入提示中。服务端生成约束后，执行器仍检查权限、当前版本、读取证据、唯一锚点与语法；格式正确不代表代码正确。 |
| 上下文选择 | 保留任务、权限、当前版本、最新公开反馈与最新有效代码片段；精确去重，先移除旧观察，再移除较旧的完整片段。源码与反馈不从中间截断。历史补丁正文只保留字符数和哈希，实际正文留在本地。 |
| 可审查记录 | 每轮保存实际 `messages.json`、`context.json`、原始响应与动作结果；清单记录选入/省略片段的路径、哈希、范围、收据 ID 和原因。省略元数据不能冒充源码。 |
| 长度目标 | 默认单次约 12,000 个**估算** Token，包含格式 Schema 开销；它是工作目标，没有累计 Token 截止。保护内容本身超目标时完整发送，标记 `protected_over_target`，不假装满足容量。 |

上下文视图不撤销此前合法读取产生的能力；编辑仍须匹配当前工作区的有效收据。修改或回滚会让旧收据失效。上下文清单描述本轮实际发送内容，不等于全部历史读取索引。

新合同通过 `--context-contract` 显式启用，协议为 `public-feedback-actions-v2-context-v1`。不加开关仍走上一阶段默认行为；旧 v1、local50、Harness² 的执行接入未改变。新协议不能继续套用历史分数进行效果比较。

## 本轮验收

- **150 项离线测试通过，8.04 秒**：包括 Schema 六分支与畸形输出、上下文保留/省略、无副作用拒绝、请求计数、旧反馈及本地 Provider 兼容；Mock 网络断言仍关闭 thinking、代理和重定向，并保留原生用量。
- **3 项真实 Docker 回归通过，29.02 秒**：原完整修正与两类取消机制正常。
- **新合同 CLI 录制回放通过**：5 次请求、3 次读取、2 次补丁、3 次公开验证；复现/保持检查依次失败/失败→失败/通过→通过/通过，最终候选哈希对应通过记录。各轮上下文清单保存，模型调用为 0。
- **本地兼容验证 3/3 通过**：Ollama `0.40.9`、`qwen3.5:27b`、thinking=false，分别生成 finish、read_symbol、apply_patch 的指定动作；原生输入 3,340、输出 73，合计 **3,413 Token**。这些是合成格式请求，没有执行所生成的补丁，也不是三项 Issue 修复。
- 验收后所属容器无残留；Langfuse 六项服务健康，既有 Trace 的 7 条观察可回读。本轮没有向 Langfuse 验证新 Trace 摄取。

字符估算与原生用量分别记录，未知值保留 null。原生 Token 数与输出完整结束都不足以证明服务端未截断输入，因此记录仍为 `server_truncation: not_verified`；真实任务的日志与输入完整性核验留到下一阶段。不据此宣称已彻底解决长上下文问题。

证据：`.tmp/feedback-contract-20261109/acceptance-summary.json`；离线与 Docker XML、`recorded-docker/`、`ollama-smoke/` 和源码归档均在同目录。上一阶段两份原始源码已按历史 SHA 精确还原归档于 `p2-source/`，不覆盖既有结果。

## 如何使用

在项目根目录、已有 corecoder 环境中运行；临时文件保持在 D 盘，输出须使用新目录。

```powershell
$runRoot='D:\project_other\CoreCoder\.tmp\feedback-contract-replay'
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$env:TEMP=$runRoot; $env:TMP=$runRoot
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTHON_DOTENV_DISABLED='1'
$env:CORECODER_LANGFUSE_ENABLED='0'

# 本地格式兼容验证：三次短请求，不执行动作，不调用付费 API。
python -B -m repairflow.feedback_contract_smoke --output "$runRoot/ollama"
```

对已有三文件验收示例，可复用[上一阶段的完整 CLI 命令](feedback-actions-v2-20261108.md#录制响应入口)，追加 `--context-contract`，并把输出改成新的 D 盘 `.tmp` 目录。`--context-target-tokens` 可调整估算工作目标；最大反馈请求仍为 20 次，读取、错误响应和补丁均占一次。该 CLI 仍强制录制响应，真实 Issue 模型入口另行接通。

实现：[Schema 与解析](../repairflow/feedback_actions.py)、[上下文构建](../repairflow/feedback_context.py)、[反馈入口](../repairflow/feedback_repair_v2.py)、[短请求验证](../repairflow/feedback_contract_smoke.py)。接口依据：[Ollama Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)、[Chat API](https://docs.ollama.com/api/chat)。本项目的 Schema 与上下文策略为自有实现。

下一步固定五项开发案例，接通基础 Agent 的真实模型反馈入口与逐调用用量/轨迹，在公开检查之外后验独立评分；不启动完整 50 项或逐任务 Harness² 搜索。
