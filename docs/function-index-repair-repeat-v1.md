# 固定函数检索修复协议：三轮重复验证

## 做了什么

新增 `docs/experiments/repeat_function_index_repair_v1.py`，在不修改单轮运行器或 Worker 的情况下执行三轮新对照。每轮七个 Click 开发任务、每任务两个策略，共 42 次新修复；上一轮历史 14 次结果不纳入本次计数。

两组仍为 Python 40 行块与完整函数种子。证据、模型摘要、系统提示、公开描述、允许文件、预算、单次 edits 补丁和 Target/Controls 协议与上一轮一致，不重新检索或根据失败重写 Prompt。重复轮次按顺序执行，每轮保留相同的任务间交替组别顺序；每分支从干净 before 副本开始，不复用补丁或对话。

固定 Ollama `qwen3.5:27b`、temperature 0、reasoning none、输出上限 2,048 tokens、总预算 15,000 tokens、证据预算 6,000 字符。每分支一次模型调用，无工具或失败重试。温度为 0 不作为确定性保证，汇总实际状态和 Prompt 哈希。

运行前冻结全体证据与实现摘要；每轮检查身份，单轮运行器在每分支重新核验证据与源码版本。中途停止时聚合已有分支，缺失配对单列 incomplete，不视为失败或完成；重复任务、重复分支和未知策略会被拒绝。用量缺失沿用单轮规则，不当作零成本。

## 指标含义

- **调用级通过数**：每策略最多 21 次；需要 Target 与 Controls 同时通过。
- **任务级重复通过数**：每任务、每策略通过 0～3 次，标明是否重复稳定。
- **配对结果**：每个任务在同一轮的两策略构成一对，分别计 both_passed、function_only、line_only、both_failed。
- **Prompt 一致性**：同任务同策略的三轮 Prompt 哈希必须齐全且相同；状态稳定要求三轮齐全且分类相同。

42 次调用来自 **7 个唯一开发任务**，不是 42 个独立缺陷；21 对也不是 21 个独立任务。重复只检查同环境可复现性，不是留出验证，不按 pass@3 或显著性检验报告泛化收益。

## 实测结果与决策

三轮均完整完成，每轮行块 0/7、函数 1/7；总计行块 **0/21**、函数 **3/21**。三次成功全部来自同一个任务 invoke-missing，它在函数组 **3/3 通过**，行块组 **0/3 通过**。其余六项任务两组均未通过，没有新增成功任务。

| 任务 | 行块三轮通过数 | 函数三轮通过数 |
| --- | ---: | ---: |
| help-eagerness | 0/3 | 0/3 |
| flag-default-map | 0/3 | 0/3 |
| resource-exception | 0/3 | 0/3 |
| flag-envvar | 0/3 | 0/3 |
| prompt-suffix | 0/3 | 0/3 |
| invoke-missing | 0/3 | **3/3** |
| shared-default | 0/3 | 0/3 |

21 个配对中，function_only 为 3、both_failed 为 18，line_only 与 both_passed 均为 0；没有缺失配对。14 个“任务 × 策略”组的三轮 Prompt 哈希全部一致，状态分类全部一致。这里的状态稳定不代表补丁字节或内部推理完全相同。

行块失败分类为 15 次 failed_verification、6 次 invalid_patch；函数为 18 次 failed_verification。没有 Token 预算停止、超时或执行错误，所有 before 快照经每轮运行器复核保持不变。

| 三轮合计 | Python 行块 | 直接函数 |
| --- | ---: | ---: |
| Prompt tokens | 47,148 | 44,451 |
| Completion tokens | 5,109 | 6,594 |
| 已计量总 tokens | 52,257 | 51,045 |
| Worker 进程耗时 | 195.79 秒 | 216.36 秒 |
| 用量 / metrics 缺失 | 0 / 0 | 0 / 0 |

本轮新增修复调用 42 次，Embedding 调用 0。函数组少用 1,212 tokens，但耗时更长；耗时包含进程启动、服务缓存和模型调用，第一轮同时运行了项目回归测试，不作为冷启动或稳定性能对照。

确认了一个开发案例在同环境下的可复现收益，也确认其余失败并非单次偶发。保持默认引擎，将直接函数策略保留为实验候选。重复轮次没有增加任务多样性，下一步建立**未参与策略设计的真实任务准入清单**：固定候选选择与排除规则，核验 before 的失败、after 的通过及 Controls 保留行为，冻结公开描述、提交摘要和评分协议，再评估已有两种策略。不得看模型成败后挑选任务，或把这七项开发任务改称留出集。

新增 8 项测试覆盖配对四种结果、不完整配对、Prompt/状态变化、重复和未知分支、子运行中断保留及非法重复次数。相关测试 **14 passed**，全量 **746 passed、1 skipped**；Ruff 与 Git diff 空白检查通过。

## 身份与复跑

```text
engine:       c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd
repair model: 7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e
observations: d2367ad4330c4b83fe9921482fba4043e6640bbec521daad5dde88defb7b7479
evidence:     6380da2dcc0d0b64ff5f48c30cb1c380ef4476cd6a78008407687f123eaf3145
single runner:97d6d3af30723894b49ee0ff340ba8bb34b25b18839d728e6c7546df0d9d0aac
repeat runner:cc8f17534f9efe3f617e5bc6eb1b7923752663e2f25520b41698dfbac015c0ed
```

证据文件保留上一轮 Windows JSON 字节格式；源码原文保持 JSON 转义，不改变源码换行。

corecoder 环境、项目根目录执行。需保留准入快照与冻结审计目录，输出目录须不存在：

```powershell
python -m pytest tests/test_repeat_function_index_repair.py tests/test_function_index_repair.py -q
python -m docs.experiments.repeat_function_index_repair_v1 --source .tmp/real-defects/function-index-audit-v1-corpus-control --output .tmp/real-defects/function-index-repair-repeat-rerun --repeat 3
```

产物 `.tmp/real-defects/function-index-repair-repeat-v1`：根目录 protocol.json、evidence.json 和 experiment.json 记录重复配置、配对与逐任务/逐轮汇总；repeat-01～03 各自保留完整单轮协议、分支响应、Trace、补丁与独立验证日志。`.tmp` 不入 Git，原始产物需另行归档。
