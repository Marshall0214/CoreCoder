# 修正评分后的三轮新模型对照

## 结果

18 次新调用全部完成；每轮行块通过 1/3、完整函数通过 2/3。三轮合计行块 **3/9**、完整函数 **6/9**。差异只来自颜色校验任务，不能将三轮重复当作九项独立缺陷。

| 任务 | 行块（三次） | 完整函数（三次） |
| --- | --- | --- |
| usage-empty | 0/3，均 invalid_patch | 0/3，均 failed_verification |
| echo-empty-bytes | 3/3 | 3/3 |
| style-color-validation | 0/3，均 invalid_patch | 3/3 |

9 个配对中，双方失败 3、双方通过 3、仅函数通过 3、仅行块通过 0。六个任务/策略组合的 Prompt 与状态跨轮一致。与上一轮相比，18 次新调用的 Prompt 摘要及 patch.diff 摘要全部相同；这是相同输入下的复现证据，不是更广泛的缺陷覆盖。

| 策略（九次合计） | Prompt Token | Completion Token | 总 Token | Worker 秒 |
| --- | ---: | ---: | ---: | ---: |
| 行块 | 21774 | 1536 | 23310 | 62.8017 |
| 完整函数 | 21315 | 4761 | 26076 | 133.3811 |

两组 usage 完整，无预算超限、超时或基础设施错误。函数总 Token 约多 12%；Worker 时间包含子进程开销，不能解释为模型纯推理时间。passed 仍须同时满足补丁合法性、Target 和 Controls。

完整结果 `.tmp/real-defects/validation-repeat-v2/experiment.json` 的 SHA256 为 `4e762eca3e996f814e1a02339631fc3bb6e85de8466267cafaf5cc22295e7ecf`。本轮没有追加 Embedding 请求，18 次模型调用均独立生成补丁，未复用旧回答。

## 目的与协议

上一轮颜色校验检查包含公开需求未要求的错误文案约束，事后校正六个原补丁后，行块通过 1/3、完整函数通过 2/3。本轮在新模型调用前冻结修正后的评分，以三轮新调用检查同一批任务的结果稳定性；旧调用不并入统计。

固定三项 Click 任务：usage-empty、echo-empty-bytes、style-color-validation。每项每策略三次，共 18 次调用、9 个配对，仍然只有 **3 个独立任务**。模型、预算、关键词检索、单次片段补丁协议沿用前轮；证据摘要与前轮完全一致。仅颜色任务采用 v2 检查，其余检查不变。

评分规则、模型配置、轮数、证据摘要与顺序在 `docs/experiments/validation-prospective-v2.json` 中冻结，SHA256 为 `6fffda44dac19694af1776a2a82f48330aebcc609122fff84d86ea18f7105b92`。`validation_repeat_v2.py` 固定该摘要并校验原清单、源码、策略及新检查版本。每轮各任务两种策略交错，第二轮反转顺序；每次新建工作区，不复用上轮补丁或反馈。

全部公开证据在评分材料打开前生成并写盘。父进程重新检查 before 目标失败、after 目标通过和两边 Controls 通过；每次调用前校验评分及适配代码摘要。模型只收到公开需求、允许文件及证据。失败与已完成的部分结果逐次落盘，不筛任务或只保留成功调用。

默认 corecoder/evals 引擎未改；不增加工具、依赖展开、反馈或重试。模型仍为 qwen3.5:27b，temperature=0、reasoning=none，证据上限 6000 字符、输出 2048 Token、总预算 15000 Token、上下文 16000，Worker 600 秒、验证 15 秒。

## 复现与证据

```powershell
python -m pytest tests/test_validation_repeat.py -q
python -m pytest tests -q
python -m docs.experiments.validation_repeat_v2 --output .tmp/real-defects/validation-repeat-v2-rerun
```

运行需要已冻结的 `.tmp/real-defects/validation-admission-v1-final` 准入产物、其记录的 Click 独立测试环境，以及已安装且身份匹配的 Ollama 模型。输出目录必须不存在。本轮产物保存于 `.tmp/real-defects/validation-repeat-v2`：protocol、observations、汇总 experiment，以及各 repeat 的请求、回答、Trace、补丁和 Target/Controls 日志。产物受 .gitignore 忽略，需要独立归档。

新增测试检查评分篡改提前拒绝、全部证据先生成、模型输入隔离、18 个新工作区、跨轮策略顺序反转、正确使用颜色 v2 检查，以及中断时保留部分结果。配对统计和 Prompt 一致性沿用已经测试的聚合器。

新增测试 **3 passed**；全量回归 **778 passed、1 skipped（82.09 秒）**，新增代码 Ruff 通过。

## 解释边界

本轮评分在新调用前冻结，属于前瞻评分；任务曾被查看与评测，**不是新的盲测任务**。重复调用不是新增缺陷样本。passed 仅代表独立 Target/Controls，通过不等于完整上游测试或生产可靠性。相同 Prompt 与状态只能说明本批受控复现，不能证明随机性消失、统计显著或跨仓库泛化。

## 下一步

后续进展：ItsDangerous 三项历史行为任务已完成第二仓库准入和冻结，见 [second-repo-admission-v1.md](second-repo-admission-v1.md)。单文件诊断表明 none-salt 并非必须多文件修复；本轮未追加模型运行。

结束本批重复运行，保留函数策略为可选实验分支。下一步补充另一个 Python 仓库中未参与策略设计的历史缺陷，先建立公开需求及 before/after/Controls 独立准入，再按相同冻结协议比较；优先补足跨文件行为链任务，分别报告单文件与跨文件结果。候选无法准入时记录原因，不根据模型修复结果筛选。本批 usage 失败保留为开发诊断材料，不据此修改新验证任务的上下文或评分。
