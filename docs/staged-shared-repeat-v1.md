# 固定检查点的补丁三轮复验 v1

## 要验证什么

共享定位的单轮重放中，read-first 通过 2/7，seed-first 通过 0/7。本轮固定同一批 7 份检查点，每个策略各重复三次补丁请求，验证这个趋势是否重复出现；不重新定位，不改变修复实现或模型。

这是对固定证据条件下补丁输出的复验，不覆盖不同定位轨迹、不同仓库或留出任务。三次请求也不是三个新的缺陷；temperature=0 不代表服务端严格确定性。

## 冻结与核对

协议为 `evals/real_defects/staged-shared-repeat-v1.json`，保存 7 份上轮检查点的路径、原始文件 SHA-256、检查点哈希、候选池哈希及共享定位 Token。修复源码仍为 `c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd`；模型摘要仍为 `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`。

复用 staged-suite-v1 的任务、准入及 RunConfig：qwen3.5:27b、temperature=0、reasoning_effort=none、总预算 30k、证据上限 6,000 字符、上下文预算 16k、补丁输出上限 2,048、Worker 超时 600 秒。定位费用参与剩余预算计算，补丁阶段仍最多 15k；未提高预算。

按任务和轮次交替两种策略的先后顺序，21 个配对顺序在执行前写入协议。每次补丁都使用原始源码的新副本，父进程分别独立评分；隐藏测试及另一个分支的结果不进入模型输入。取消保持实验未完成，其他失败保留在分母中。

本轮共 42 个分支，每条只有一次实际补丁调用。验收时核对：

- 42 条记录齐全，每个任务、策略、轮次组合只出现一次。
- 同一任务全部重复使用相同检查点、候选池、源码和非证据指令；同一策略的完整补丁提示哈希也一致。
- 源码、模型、配置和检查点文件不变；没有新定位调用。
- Worker 用量只统计本轮补丁调用，共享定位成本不计为本轮实际消费。

## 用量口径

上轮 7 份检查点的定位记账合计 63,313 Token，已经在上轮发生。本轮实际用量为 42 次补丁调用之和，不再加入这些历史 Token。

某策略一轮的流水线等效记账 = 63,313 + 该策略本轮补丁记账；某策略三轮等效记账 = 3 × 63,313 + 三轮补丁记账。两个策略三轮等效总和包含 6 × 63,313 历史定位记账，不能当成实验实际费用。

未知提供方用量仍标记未知，预算记账可能使用保守预留；不将它称为准确账单。正常行为检查只覆盖已有 Controls，不是完整上游测试。

## 复跑

```powershell
python docs/experiments/staged_shared_repeat_v1.py --validate-only --admission original=.tmp/real-defects/mixed-original-admission-v1/admission.json --admission crossfile=.tmp/real-defects/crossfile-admission-v2/admission.json --admission expansion=.tmp/real-defects/expansion-admission-v1/admission.json --output .tmp/real-defects/staged-shared-repeat-v1-rerun
```

移除 `--validate-only` 正式执行；输出必须是不存在的新目录。入口只编排现有 staged-replay，未改变 `corecoder/` 或 `evals/` 中的修复实现。

**需要保留上轮 `.tmp/real-defects/staged-shared-replay-v1/` 中的原检查点。** 它们被 Git 忽略，仅克隆仓库无法得到这些冻结产物。文件缺失或哈希不符时入口在调用修复模型前失败，不重新定位来代替。若重建定位结果，应另建实验版本。

## 本轮结果

42 次已完整结束，上轮 14 次补丁试跑不并入本轮。每条只有一次实际补丁调用，没有重新定位；所有 Worker 完成并修改了源码，未出现未知用量或越界修改。

| 指标 | read-first | seed-first |
| --- | ---: | ---: |
| 独立验收通过 | 6/21 | 0/21 |
| 每轮验收通过 | 2/7、2/7、2/7 | 0/7、0/7、0/7 |
| 公开正常行为检查通过 | 15/21 | 21/21 |
| 实际补丁调用 | 21 | 21 |
| 实际补丁 Token | 58,980 | 61,830 |
| 三轮流水线等效 Token | 248,919 | 251,769 |

| 任务 | read-first | seed-first |
| --- | ---: | ---: |
| click-help-eagerness | 0/3 | 0/3 |
| click-flag-default-map | 3/3 | 0/3 |
| click-resource-exception | 0/3 | 0/3 |
| click-flag-envvar（跨文件） | 0/3 | 0/3 |
| click-prompt-suffix | 0/3 | 0/3 |
| click-invoke-missing | 3/3 | 0/3 |
| click-shared-default | 0/3 | 0/3 |

本轮实际消费为 **42 次模型调用、120,810 Token**。等效记账合计 500,688 Token，其中包含 6 × 63,313 的历史定位成本，不能当成本轮实际消费。两种策略每轮补丁用量分别固定为 19,660、20,610 Token。

21/21 配对的候选池和非证据指令一致。每个任务同一策略三轮的完整提示哈希一致，原始补丁响应也逐字节一致；检查点文件、模型摘要及修复源码哈希均保持不变。这说明当前服务在这些固定输入下可复现，不能把三次完全相同的重放当成三个独立样本来增加统计置信度。

原始结果及核对摘要在 `.tmp/real-defects/staged-shared-repeat-v1/experiment.json`、`analysis.json`，各分支目录保留 Trace、补丁和独立评分。这些产物被 Git 忽略，需要另行保存。

## 决策与下一步

保持 read-first 默认，不推广 seed-first。本轮没有观察到符号优先的修复收益；其公开检查全部通过，但缺陷验收仍全部失败。跨文件任务仍未修复，现有七个任务全部是开发集，不支持跨仓库泛化结论。

停止继续重复同一输入。下一步离线诊断公开需求对应的证据覆盖：哪些相关符号已进入候选池、哪些被截断、哪些在上下文装填时丢失。诊断依据公开描述、原始源码和冻结检查点，不以隐藏测试或参考补丁位置指导选择；再决定是否需要改变检索或上下文策略。新增跨文件、其他仓库与留出任务仍是后续验收要求。

## 验证

本轮共享重放及分阶段修复相关测试 14 passed；新实验入口 Ruff 通过，冻结协议预检通过。修复实现未改变，未重跑全量测试；上轮全量结果为 600 passed、1 skipped。
