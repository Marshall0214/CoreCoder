# 五项本地反馈闭环验收

状态（2026-11-09）：五项首次运行、独立评分、Langfuse 回读与审计完成。独立通过 **1/5**，公开通过 **1/5**，基础设施错误 **0**。本轮用于验收已知开发案例的执行机制，不能与历史 DeepSeek 或其他 50 项协议计算提升。

## 完成的链路

新增 `evals.feedback_pilot_v2`，连接首轮探索、新反馈动作循环与后验独立评分；新增保留动作 Schema 的用量适配器、反馈事件记录和小批次 Langfuse 发布器。

```text
冻结任务与实现 → 零模型准入 → 探索进程 → 核对、合并候选
                                          ↓
独立评分、报告与回读 ← 反馈进程终止 ← 读取—修改—公开验证
```

探索会导出部分文本文件，不能直接将省略项当成删除。运行器先核对工作区、Diff、清单与哈希，再把真实修改叠加到完整基线副本。公开反馈仅使用 `case.harness`；独立 `case.checks` 在 Agent 结束后使用，不进入模型请求。

| 固定项 | 本轮设置 |
| --- | --- |
| 模型 | 本地 `qwen3.5:27b`，thinking=false；digest `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e` |
| 探索 | 最多 20 次请求、6 次编辑尝试、1200 秒；保留旧探索的重复/错误停止规则 |
| 反馈 | 另计最多 20 次请求、1200 秒，使用新上下文合同与 Schema；没有重复读取提前停止规则 |
| Token | 无累计或输出 Token 截止；单次请求最多 480 秒，Provider 上下文 65,536，反馈估算工作目标 12,000 |
| 工具与评分 | 原有读写白名单、唯一锚点、语法检查与 Docker 边界；终止后独立 Target/Controls 评分 |
| 实验 | `feedback-actions-pilot-five-v1`；无 Harness² 搜索、旧候选复用、付费 API 或失败重跑 |

新合同只用于反馈阶段。初始与最终模型/沙箱身份一致，22 份运行源码及归档、20 个原始输入目录的哈希核验通过。

## 逐项结果

调用列为探索 + 反馈；Token 包含失败任务的两阶段原生用量。

| 任务 | 主要缺陷 | 调用 | 反馈读取 / 补丁 | 公开 / 独立 | Token |
| --- | --- | ---: | ---: | --- | ---: |
| toolz-join-unmatched | 外连接未匹配项触发 NameError | 7 + 6 | 5 / 1 | 通过 / 通过 | 60,254 |
| itsdangerous-none-salt | salt=None 默认值处理 | 5 + 20 | 20 / 0 | 失败 / 失败 | 104,732 |
| boltons-split-zero | maxsplit=0 的源值处理 | 6 + 20 | 20 / 0 | 失败 / 失败 | 118,927 |
| click-style-color-validation | 调色板 0 与颜色合法性 | 8 + 20 | 19 / 0 | 失败 / 失败 | 194,859 |
| more-negative-range-slice | numeric_range 负步长切片 | 13 + 20 | 20 / 0 | 失败 / 失败 | 213,666 |

合计 **125 次调用**：探索 39、反馈 86；输入 **687,387**、输出 **5,051**，共 **692,438 Token**，未知用量 **0**。反馈响应 **86/86** 符合 Schema，共 84 次读取、1 次搜索、1 次有效编辑、6 次公开验证；环境重试、回滚和工具拒绝均为 0。五项独立 Controls 均通过。

Toolz 首轮重复读取后停止；反馈重新读取完整 `join`，将未定义的 `iteritems(d)` 改为 `d.items()`，随后公开与独立 Target/Controls 均通过。没有人工修改补丁。这证明一项真实的失败后再定位与修正链路，不是整体提升对照。

## 失败归因

四项失败均耗尽 20 次反馈请求，**没有提交补丁，也没有被补丁校验拒绝**。More 首轮生成过候选，但反馈没有修正。因此不能把本轮失败归因为锚点限制、沙箱故障或格式被拦截。

- **itsdangerous**：20 次都读取 `signer.py` 的 `[0:6000]`；工具明确返回下一页 `6000`，模型没有继续翻页或查看 Serializer。公开检查真实返回 None 与 bytes 相加的 TypeError。
- **Boltons**：反馈始终读取 `[0:6000]`，目标函数范围为 `[3944:6174]`，缺少末尾 174 字符；工具正确标注分页。
- **Click**：第 7、8 次反馈已完整读取 `style`、`_interpret_color`，两个函数持续保留。随后反复请求文件偏移 560/570，实际读到第 23～24 行；这些值接近目标起始行 572/583，而非字符位置 20211/20539。
- **More**：读到类起始行 2226 后，使用 `read_file(offset=2226)`，实际读到第 118 行。反馈已取得该类两页完整内容，仍重复此文件偏移 14 次。

轨迹支持“坐标语义混用与动作空转”的判断，但不能证明唯一根因。Click、More 已有完整目标代码，不能全部解释为检索不足。下一次优先在一个固定失败任务上验证读取接口与推进状态，先看能否进入编辑，不直接扩大任务或重试次数。

## 日志修正与验收

旧日志匹配规则把所有包含 `truncat` 的行当作警告。十份窗口实际只有 **125 条 `truncated=0` 正常记录，0 条明确输入截断警告**。原始日志、状态和成绩均保留；运行结束并完成源码核验后，另存审计解释、修正新运行的分类器，没有重新调用模型。

无正面警告时仍记录 `not_verified`，不能据此证明服务端完整接收全部输入，也不能将失败归因于已经确认的输入截断。

运行前相关离线测试 **98 项通过**；统计修正后运行器与日志分类专项 **47 项通过**（部分复验），Ruff 与格式检查通过。Langfuse 回读确认 **10 条推理 Trace、125 次原始调用/用量、5 份摘要与独立评分**一致；发布新增模型调用为 0，不上传代码、Prompt 或测试正文。

## 证据与复现

原始根目录：`.tmp/feedback-pilot-20261109/run/`。

- `protocol.json`、`implementation/`、`identity*.json`：实际运行版本与身份。
- `tasks/<id>/initial/agent/`、`feedback/`、`grading/`：请求、动作、上下文、补丁、公开与独立结果。
- `report.json`、`analysis.json`、`acceptance-summary.json`：结果与审计。
- `input-evidence-audit.json`、`measurement-correction.json`：日志解释与运行后修正；当前实现不能静默恢复旧协议。
- `langfuse.json`：服务端回读收据。

本地示例：[Toolz 修复反馈](http://127.0.0.1:3300/project/corecoder-issues/traces/f996a5fbf2de0ddb2e971290bf4bfffa)、[itsdangerous 读取空转](http://127.0.0.1:3300/project/corecoder-issues/traces/a5ecc1d12078cbef4305a0826e0d1f75)。

如需另开一次真实运行，在项目根目录、已有 corecoder 环境执行；使用新目录会重新产生推理：

```powershell
$runRoot='D:\project_other\CoreCoder\.tmp\feedback-pilot-new'
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$env:TEMP=$runRoot; $env:TMP=$runRoot
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTHON_DOTENV_DISABLED='1'
$env:CORECODER_TEST_BACKEND='docker'
$env:PYTHONPATH='D:\project_other\CoreCoder\.tmp\langfuse-deps;D:\project_other\CoreCoder\.tmp\workflow-deps;D:\project_other\CoreCoder'
python -B -m evals.feedback_pilot_v2 --output "$runRoot/run"
python -B -m deploy.langfuse.feedback_pilot --batch "$runRoot/run" --env-file .tmp/langfuse-local/.env
```

本轮已经结束，不自动重跑或扩展到 50 项；新协议的服务层接入仍需单独 API 冒烟。
