# 分阶段修复三轮复验 v1

## 目的与冻结条件

复验上轮 staged 试跑的 2/7 是否重复出现，检查“预算内产生修改”和“修复正确”这两件事的稳定性。本轮不修改 CoreCoder、评测引擎、Prompt、检索、预算分配或工具权限，不将隐藏验收反馈给模型。

协议为 `evals/real_defects/staged-repeat-v1.json`；复用已冻结的 staged / agent-loop 清单及同一隔离准入环境。固定 7 个 Click 开发任务、qwen3.5:27b、temperature=0、reasoning_effort=none、总预算 30k、上下文 16k、输出上限 2,048、轮数上限 32、Worker 超时 600 秒、测试超时 15 秒。

实现 SHA-256：`8a51f3addc335c708674d77d8e29df87e1e4da16ded591cdb702059f3a0738d1`；模型摘要：`7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`。运行前和每个批次前校验身份，协议校验两个清单哈希；使用新工作空间、新输出目录，保留所有失败。没有指定额外随机种子，不把 temperature=0 当作服务端严格确定性的保证。

每轮两种流程各运行 7 个任务，共 42 次，**不计入上轮 14 次试跑**。批次顺序在运行前冻结：

| 轮次 | 先运行 | 后运行 |
| --- | --- | --- |
| 1 | agent-loop | staged |
| 2 | staged | agent-loop |
| 3 | agent-loop | staged |

同一批次内保持清单任务顺序，没有并发模型请求。这不是完全随机化试验，仍可能存在运行顺序和服务状态影响。每个 suite-report 的 repetition 为 1；外层 experiment.json 的 repetition 才表示这里的三轮编号，不能把六个批次混成六轮。

## 复跑

新增的 `docs/experiments/staged_repeat_v1.py` 仅编排现有 run_suite，不改变修复实现。先验证准入、协议和本地模型身份，验证模式不会调用修复模型：

```powershell
python docs/experiments/staged_repeat_v1.py --validate-only --admission original=.tmp/real-defects/mixed-original-admission-v1/admission.json --admission crossfile=.tmp/real-defects/crossfile-admission-v2/admission.json --admission expansion=.tmp/real-defects/expansion-admission-v1/admission.json --output .tmp/real-defects/staged-repeat-v1-rerun
```

正式运行时移除 `--validate-only`，使用不存在的新目录。总入口会保留失败运行，并在六个批次完整结束后确认 42 次齐全；运行中各批次 suite-report 实时保存进展，外层计数在批次结束后更新。后续若修改修复实现，需要另建实验版本，不能沿用此协议的源码哈希。

本轮产物为 `.tmp/real-defects/staged-repeat-v1/experiment.json`、六个批次的 suite-report、每次的 Trace、候选补丁和独立评分日志。`.tmp` 被 Git 忽略，需另行保存原始产物。

## 结果

42/42 已完整完成。所有批次和单次报告的源码哈希一致；所有 Worker 的运行前后模型摘要一致；两个流程配置、任务顺序、准入记录一致。未知用量调用为 0，没有超时、API 错误、轮数停止或越界修改。Trace 核对与汇总保存在同目录 `analysis.json`。

| 指标 | agent-loop（21 次） | staged（21 次） |
| --- | ---: | ---: |
| 独立验收通过 | 0/21 | 6/21 |
| 实际产生源码变化 | 0/21 | 21/21 |
| 全任务预算停止 | 21/21 | 0/21 |
| 总已知输入+输出 Token | 533,058 | 249,110 |
| 每次平均 Token | 25,383.71 | 11,862.38 |
| 每次 Token 范围 | 22,209–27,347 | 9,370–14,872 |
| 累计任务耗时（秒） | 400.88 | 436.73 |

耗时是报告中的任务耗时之和，包含 Worker 和父进程评分，不是整场实验墙钟时间。不能根据 Token 下降宣称速度或实际账单同比下降，尤其此次在本地 Ollama 上运行。

| 轮次 | 原流程通过 | staged 通过 | 原流程 Token | staged Token |
| --- | ---: | ---: | ---: | ---: |
| 1 | 0/7 | 2/7 | 176,183 | 82,960 |
| 2 | 0/7 | 2/7 | 179,482 | 82,863 |
| 3 | 0/7 | 2/7 | 177,393 | 83,287 |

| 任务 | 原流程通过次数 | staged 通过次数 |
| --- | ---: | ---: |
| click-help-eagerness | 0/3 | 0/3 |
| click-flag-default-map | 0/3 | 3/3 |
| click-resource-exception | 0/3 | 0/3 |
| click-flag-envvar（跨文件） | 0/3 | 0/3 |
| click-prompt-suffix | 0/3 | 0/3 |
| click-invoke-missing | 0/3 | 3/3 |
| click-shared-default | 0/3 | 0/3 |

原流程的 21 次均为 cumulative_preflight，没有实际修改。staged 的 21 次 Worker 均正常完成、产生合法非空补丁，首次修改发生在第 3–5 次完成的模型调用后；因为补丁后没有模型调用，首次修改 Token 就是上述单次总 Token。定位阶段仍有预算预检查停止，但会进入补丁阶段，不能把这些事件算成全任务预算失败。

staged 的公开检查通过 17/21：resource-exception 三次均破坏正常行为，prompt-suffix 第三轮也破坏正常行为；其余公开检查通过并不代表缺陷修复成功。正常行为回归出现变化，说明“三轮验收结果一致”不等于候选补丁内容完全一致或每次都安全。父进程的回归检查仍仅覆盖已发布 Controls，不是完整上游测试套件。

## 结论与下一步

这三轮重复支持：在这 7 个已知开发任务上，组合工作流可以反复在 30k 预算内进入修改，并反复修复两个单文件缺陷；其他五个任务仍失败。Token 用量更少，但耗时略高。问题重点已从“预算内无法开始修改”转为“证据是否充分、补丁能否覆盖正确行为”。

7 个任务不是 21 个独立缺陷，三次重复也不能替代跨文件、跨仓库或留出评测；不据此推算泛化成功率或宣称统计显著提升。staged 同时改变了证据、上下文和工作流，不能将差异单独归因于检索。

下一步冻结阶段预算、工具权限和补丁输出协议，在该工作流内对证据选择及上下文组织做单因素消融；保持独立评分，不根据隐藏失败用例逐条拼接提示规则。随后补充真正跨文件及其他仓库任务并建立留出集。

## 验证记录

相关现有测试 `tests/test_real_suite.py`、`tests/test_staged_repair.py`：15 passed。实验编排脚本的 Ruff、验证模式及正式六个批次均通过。未改动修复实现，未重新重复执行上轮已通过的 590 项全量测试。

后续证据优先级试跑与候选池一致性检查见 [staged-evidence-pilot-v1.md](staged-evidence-pilot-v1.md)，本页仍保留冻结的三轮复验记录。
