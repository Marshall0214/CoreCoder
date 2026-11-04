# 前沿能力接入路线（2026-10-29）

当前目标仍是完成可运行、可演示的 Coding Agent，修复准确率优化后置。用户选择先把 Langfuse 部署到本地 Docker，数据保留在 D 盘；其他项目按用途逐项推进，不是五个必装依赖。

## 项目中的落点

| 项目 | 对应需求 | 本项目交付与验收 | 当前状态 |
| --- | --- | --- | --- |
| Langfuse | 把本地日志变为可浏览的任务执行链，区分模型、工具、测试和停止原因 | 一次任务对应一条 Trace；记录用量、错误码、公开检查与独立验收边界；脚本演示和真实模型区分 | 本地服务已上线；CLI/API 两条 Trace、14 节点、登录与重启保留已验收 |
| Harness² | 学习如何修改和比较 Agent 周边组件 | 先在独立实验目录运行无模型 demo，再设计本项目的策略适配；暂不运行模型改进实验 | 官方实现已核对，未接入 |
| Mem0 | 跨任务保存经过验证的仓库约定和经验 | 按仓库、版本、来源和验证状态隔离，支持纠正、失效和删除；记忆不得授予工具权限 | 需求设计，未接入 |
| OpenViking | 统一组织仓库知识、记忆与技能，按摘要逐层读取 | 与现有符号读取配合；命中后回到当前工作区核对版本；先与 Mem0 作为可替换方案比较 | 官方实现已核对，未接入 |
| Dream-RSI | 研究如何分配尝试与探索预算 | 独立研究模块，保持执行器/任务/评分固定后比较策略；不把离线回放当作真实修复 | 后置，未复现 |

目前先交付 Langfuse 的可观测性。之后如果继续工程扩展，优先做一个有来源、有版本和删除机制的仓库记忆功能，再选择 Mem0 或 OpenViking；Harness² 与 Dream-RSI 的研究实验另立预算，避免改变“准确率后置”的约定。

## 官方资料核对与实际限制

- [Langfuse 评测](https://langfuse.com/docs/evaluation/overview)包含代码评分、数据集和实验比较。本次只接入追踪与确定性的公开检查记录，不自动调用 LLM 裁判，也不声称已建立新评测成绩。
- [SDK 官方兼容说明](https://langfuse.com/docs/observability/sdk/overview)：Python SDK v5 对应 Langfuse v4；本轮安装 SDK 5.0.4 到 D 盘独立目录，要求 Python 3.11+，现有 corecoder 环境为 3.11.16。部署文件选择服务 4.69.0。
- [Harness² README](https://github.com/google-research/harness2)描述 Propose–Probe–Compose 与持久改进经验。官方安装要求 Linux、Python 3.12；无模型 demo 可独立学习，但不能当作本项目已获得自动改进能力。其当前任务内改进不依赖真实答案反馈，最终效果仍需独立评测。
- [Mem0 add 文档](https://docs.mem0.ai/core-concepts/memory-operations/add)区分提取式与原样存储，并支持标识符隔离。默认提取会调用模型；本项目后续需显式选择本地或人工整理方式，不能静默消耗 API。
- [OpenViking README](https://github.com/volcengine/OpenViking)把知识、记忆和技能组织为可浏览的上下文文件系统。与 Mem0 存在记忆职责重叠；当前仓库标注 AGPLv3，选型时单独核对许可范围，本轮未复制或引入其代码。
- [Dream-RSI README](https://github.com/google-research/dream-rsi)改进探索策略，固定底层 Agent、任务和评估器，使用历史探索树回放选择策略。与日常 Issue 修复服务分开建设，不把多次尝试自动当作方法提升。

## Langfuse 第一阶段

1. 本地部署文件、凭据生成和 D 盘位置检查。
2. 可选适配：任务根节点、模型/脚本响应、工具调用、Docker 检查与预算停止。
3. 保留本地 `trace.jsonl`；默认不上送源码、Prompt、补丁锚点或原始测试日志，只发送结构化摘要。
4. 默认关闭、异常不改变任务结果；API 提供 `observability.json` 与 Trace 链接。
5. 使用合成任务和脚本响应验证服务实际接收 Trace，模型调用为零。[服务器回读已通过](langfuse-server-20261029.md)；执行报告保留原始 `submitted_unconfirmed`，另存独立回读确认，不改写历史状态。

部署与接入步骤见 [本地 Langfuse](langfuse-local.md)。后续功能逐项验收，未完成内容不得写成简历成果。

后续[真实用量验收](langfuse-token-usage-20261030.md)已完成：本地 Qwen3.5 27B 关闭 thinking，1 次调用、1,027 Token，在 Ollama、本地与服务器三处一致；脚本改为普通 Span，未知用量与实测零区分。它属于工程验收，没有新增准确率对照实验。

[运行学习与故障演练](langfuse-operations-20261030.md)进一步区分 Web 存活、依赖/Worker 健康、旧数据可读和新任务入库。两项实际演练均使用脚本响应；恢复后六个服务正常，未调用模型。备份与隔离恢复仍待实施；自动告警和离线补传尚未实现。

随后按用户选择接通 [SWE-bench Verified Mini 首项](swebench-mini-20261030.md)：固定社区 50 项清单，首项 unchanged 目标 0/2、回归 77/77，参考补丁目标 2/2、回归 77/77；采用官方 5.0.2 脚本/评分并关联一个 Langfuse 数据集、两个结果导入实验。模型调用 0；这属于评测器验收，尚非 Agent 在该基准上的修复结果。

[首次实际 Agent 运行](swebench-agent-20261030.md)随后完成：同一项本地 Qwen 6 次调用、19,364 Token，重复读取停止、未修改、官方目标 0/2。已关联真实生成 Trace、后置评分和同一数据集实验，不将结果导入伪装成再次推理。
