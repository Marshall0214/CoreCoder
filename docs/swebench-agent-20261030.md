# SWE-bench Mini：第一次本地 Agent 修复尝试

本轮把上一阶段的“未修改/参考补丁控制组”扩展为**真实本地模型搜索仓库、读取代码、生成候选，再独立评分**。只运行 `django__django-11790` 一次，没有使用付费 API，也没有根据隐藏测试失败反馈重新请求模型。结果是 **未修复**。

## 1. 端到端流程

```text
四个公开字段 → 固定 commit 的仓库文本 → Agent 搜索/读取/编辑循环
                                               ↓ 终止后
                                        保存 patch.diff
                                               ↓ 新进程、新容器
                                      官方测试脚本与独立评分
                                               ↓
                              Langfuse 真实推理 Trace + 实验结果关联
```

Agent 进程只读取 `agent/input.json` 的 instance_id、repo、base_commit、problem_statement；不读取 `grader/instance.json`。控制端检查公开输入哈希，从既有固定镜像执行 `git archive <base_commit>`，导出 3,076 个 UTF-8 文本文件、约 19.4 MB。没有导出 `.git`、未来提交、容器准备提交或控制端/评分目录；二进制、大文件、非文本和链接跳过并记录。

公开的原始测试可以读取，评测补丁新增的测试和标签不可见。模型没有得到来自参考补丁的目标文件列表；编辑范围由仓库现有非测试 Python 文件推导，测试、setup.py、conftest.py 只读。这是可读文本仓库视图，不是包含所有构建资源的完整工作区。

工具包括 `search`、`list_files`、`read_file`、`read_symbol`、`apply_patch`、`finish`。搜索是有返回上限的字面量扫描，不依赖旧检索器的 500 文件索引；读取有明确 next_offset。编辑复用现有版本哈希、已读证据、唯一锚点和 Python 语法校验，在最小暂存视图验证后发布。模型不能调用任意 shell、联网或运行隐藏评分；候选代码不在宿主机执行。

## 2. 固定配置与实际结果

| 项目 | 设置/实测 |
| --- | --- |
| 本地模型 | 已安装的 `qwen3.5:27b`，temperature=0，think=false |
| 最大动作轮数/编辑尝试 | 20 / 6 |
| Token 预算 | 30,000，估算预检 + 返回 usage 控制，非账单绝对上限 |
| 控制器上下文/单次输出上限 | 估算 16,000 / 2,048；输出按剩余预算收缩 |
| 模型服务窗口 | 复用 OllamaProvider，请求 num_ctx=65,536；不等同于控制器估算上限 |
| 任务 deadline | 1,200 秒；提供商按剩余时间限制请求，每次至多 480 秒；尚非外部 Worker 级硬终止 |
| 实际执行时间 | Agent 34.671 秒；后置评分 5.032 秒 |
| 实际模型调用 | 6 次 |
| 实测 Token | 输入 19,232 + 输出 132 = **19,364** |
| 云 API 费用 | $0；电费/本地硬件成本未知 |
| 修改文件/补丁 | 0 个 / 空补丁 |
| 停止原因 | `repeated_action_limit` |
| 官方目标测试 | 0/2 通过 |
| 官方回归测试 | 77/77 通过 |
| 官方 resolved | false |

沿用上一阶段固定的 Mini/官方数据 revision、官方 Harness 5.0.2 及不可变镜像 ID。评分使用不同进程中的可信评分记录、新的禁网受限容器、官方脚本/解析器/评分器；评测结果没有回到 Agent 上下文。空候选也实际评分，没有只凭“未编辑”推断测试结果。

这是一项开发任务上的一次真实尝试，不是 Mini 50 项准确率，也不与历史 `47/50` 比较。

运行后只读记录了本机模型 digest 和 `Q4_K_M` 量化信息，保存在证据包中；这是运行后的模型清单快照，不伪装成推理前的采样记录。

## 3. 它实际做了什么，为什么失败

1. 搜索 `AuthenticationForm`，结果已包含真正定义位置。
2. 读取 `django/contrib/auth/forms.py` 的字符区间 `[0, 6000)`。
3. 读取 `[6000, 12000)`。
4. 再次请求 offset=0。
5. 又请求 offset=0。
6. 再次提出相同读取，重复动作保护停止，未执行第四次相同读取。

事后按原文件 AST 审计，相关构造函数字符范围为 `[6243, 6930)`；**第 4、5、6 次请求已带有覆盖完整构造函数的当前片段**。因此本例不是“搜索不到目标”、也不是缺少该函数或 Token 预算耗尽；可观察到的直接问题是模型没有从阅读推进到补丁动作。

不能据此断言根因一定是模型能力、提示词、JSON 工具协议或历史组织中的某一个因素。后续有价值的对照是：显式记录已读范围/当前阶段，对无新增信息的重复读取给出进度反馈，或引导读取完整符号；不能拿本次隐藏测试答案来定制补丁或追加重试后只报告成功。

首次原始 actions.json 记录了 5 个已执行动作；第 6 次在保护分支停止，响应与最终状态保留。随后补齐“被阻断动作也写入 actions/Trace”的记录逻辑，并用离线单测验证；**未为此重新调用模型或改写首次产物**。

## 4. Langfuse：推理与评分都能核对

- [真实推理 Trace](http://127.0.0.1:3300/project/corecoder-issues/traces/f94a07721f4087b3aeaa4745a6cdd4e6)：6 个真实 GENERATION，服务器回读的输入 19,232、输出 132 与本地报告一致，节点均结束。无源码、完整 Prompt、补丁锚点或原始测试日志上传。
- [本次 Agent 实验](http://127.0.0.1:3300/project/corecoder-issues/experiments/results?baseline=d272bbebaedba142)：与原有未修改/参考补丁共用同一个冻结数据集，回读验证官方 resolved=false、目标比例 0、回归比例 1、模型调用 6、`actual_total_tokens=19364`。

实验导入不会再次调用模型，标记 `source=local_agent_result_import`，并链接原始推理 trace_id。实际 Token 在原始 GENERATION 中记录一次；实验表用自定义 `actual_total_tokens` 评分比较，**不复制生成节点来制造第二份 Token 消耗**。实验导入的自动延迟/Token 列不代表原始推理的耗时/用量，应查看关联 Trace 和输出指标。

Agent 根节点只描述推理阶段，没有伪造“公开测试失败”评分；独立评分完成后给该原始 Trace 追加 `official_resolved=false`，并在实验保存正式结果。原始报告的 `official_grading=not_run` 描述当时的 Agent 阶段，后置 grading/report.json 单独保存验收结论，不覆盖原始历史。

## 5. 复现与制品

基于[首项准备与镜像说明](swebench-mini-20261030.md)，运行 Agent 时使用 corecoder 环境及可选 Langfuse SDK，勿加载评分器依赖到 Agent 进程：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='D:\project_other\CoreCoder\.tmp\langfuse-deps;D:\project_other\CoreCoder'
$env:PYTHON_DOTENV_DISABLED='1'
$env:CORECODER_HOME='D:\project_other\CoreCoder\.tmp\swebench-agent-state'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
$env:CORECODER_LANGFUSE_ENABLED='1'
$env:CORECODER_LANGFUSE_ENV_FILE='D:\project_other\CoreCoder\.tmp\langfuse-local\.env'
$env:NO_PROXY='127.0.0.1,localhost,::1'
python -B -m evals.swebench_agent --entry .tmp/swebench-mini-entry-20261030 --image-id sha256:e0e74c3332a0c6bd8b1c8409fd966da5dc7b8836d9c4e0fa139908068d8f1d21 --output .tmp/swebench-mini-agent-002 --model qwen3.5:27b
```

该命令会触发新模型调用；本轮只执行过一次，复现必须使用新输出目录。仅评分已有候选时，另开终端使用评分器依赖，**不再调用模型**：

```powershell
$env:PYTHONPATH='D:\project_other\CoreCoder\.tmp\swebench-v5-deps;D:\project_other\CoreCoder\.tmp\swebench-deps;D:\project_other\CoreCoder'
$env:PYTHON_DOTENV_DISABLED='1'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
$env:HF_HOME='D:\project_other\CoreCoder\.tmp\swebench-cache\hf'
python -B -m evals.swebench_mini grade-candidate --entry .tmp/swebench-mini-entry-20261030 --candidate .tmp/swebench-mini-agent-002/patch.diff --image-id sha256:e0e74c3332a0c6bd8b1c8409fd966da5dc7b8836d9c4e0fa139908068d8f1d21 --output .tmp/swebench-mini-agent-grade-002
```

再切回 SDK 依赖导入已有结果：

```powershell
$env:PYTHONPATH='D:\project_other\CoreCoder\.tmp\langfuse-deps;D:\project_other\CoreCoder'
python -B -m deploy.langfuse.swebench_agent --entry .tmp/swebench-mini-entry-20261030 --attempt .tmp/swebench-mini-agent-002 --grading .tmp/swebench-mini-agent-grade-002 --env-file .tmp/langfuse-local/.env --output .tmp/swebench-mini-agent-langfuse-002.json
```

本轮原始产物：`.tmp/swebench-mini-agent-20261030/`、`.tmp/swebench-mini-agent-grade-20261030/`、`.tmp/swebench-mini-agent-langfuse-20261030.json`。全部新增数据在 D 盘，没有重启 8001 或 Langfuse 服务。

新增 12 项离线代码测试，覆盖公开输入白名单、归档路径/历史隔离、仓库搜索、已读锚点、只读测试、语法失败不发布、重复动作停止、真实生成 Token 回读和未知用量。与既有相关测试合计 **81 项通过**，Ruff 通过；这不是 81 项 Issue 修复结果。冻结摘要、上下文审计、代码/测试快照与服务器回执见[清单](swebench-agent-20261030.json)。
