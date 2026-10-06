# 共享定位证据的补丁重放 v1

## 为什么继续做

上轮证据优先级试跑中，3/7 个配对的定位候选池不同。初始提示一致仍不能保证实际阅读动作相同，因此需要让两个补丁分支共享一次定位结果。

本轮每个任务只运行一次只读定位，保存定位检查点；随后从相同原始源码创建两个独立副本，分别使用 read-first、seed-first 选择证据、调用一次补丁模型并独立评分。不重新定位，也不把一个分支的补丁或验收结果提供给另一分支。

## 实现

- `evals/staged_repair.py` 拆出 localize_staged 和 patch_staged，原 run_staged 仍串联两阶段，默认 read-first。
- 检查点保存公开任务描述、全部允许源码的哈希、冻结配置、实现版本、原始候选池、定位用量和阶段信息；校验整体、候选池及源码。证据文本必须与所声明的源码行范围一致，兼容原始 CRLF 和阅读片段的行分隔格式。
- 重放在模型调用前验证任务、写入范围、配置、实现、源码、证据内容及预算信息。过期或不匹配的检查点不允许进入补丁请求。
- 新增 staged-localize / staged-replay 工作流和 `--localization-checkpoint`；只有 replay 接受该参数。定位状态为 localized，不计为修复成功。
- 每个重放报告记录 checkpoint hash、candidate pool hash、evidence hash，以及去掉 fragments 后的 patch_non_evidence_hash；因此可以逐任务核对其他补丁指令与预算状态是否相同。

工具权限、公开问题、6,000 字符证据上限、模型、阶段预算、JSON 补丁校验及父进程隐藏评分保持原协议。优先级仍可能同时改变内容与排列顺序，本轮不拆分这两种效应。

## 用量如何统计

定位最多使用总预算的 40%，补丁最多 50%，10% 为未使用的模型预算余量。30k 配置对应 12k / 15k / 3k。重放的剩余任务空间扣除共享定位记账，再计算补丁上限；不会为了重放获得更大预算，也不修改 BudgetLLM 的已调用计数来虚构定位请求。

重放 Worker 的 metrics 仅包含该分支实际补丁调用。budget_accounting 分别记录共享定位记账、补丁记账、当前 Worker 记账以及单条流水线的等效总记账。

```
实验实际调用成本 = 一次定位 + read-first 补丁 + seed-first 补丁
read-first 等效流水线成本 = 共享定位 + read-first 补丁
seed-first 等效流水线成本 = 共享定位 + seed-first 补丁
```

不能把两条等效流水线成本相加当作实验实际成本。用量缺失时 metrics 保留未知，预算沿用预留值；预算记账不是提供方收费硬上限。公开验证没有模型调用，当前仍没有验证后的模型恢复轮次。

## 冻结及复跑

协议是 `evals/real_defects/staged-shared-replay-v1.json`，复用 staged-suite-v1 的完整 7 个 Click 开发任务。固定 qwen3.5:27b、总预算 30k、temperature=0、reasoning_effort=none、上下文预算 16k、输出上限 2,048、Worker 超时 600 秒、测试超时 15 秒。

实现摘要为 `c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd`；模型摘要为 `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`。每个任务两个分支的先后顺序提前固定，按任务交替；这不是完全随机化。

```powershell
python -m pytest tests -q
python docs/experiments/staged_shared_replay_v1.py --validate-only --admission original=.tmp/real-defects/mixed-original-admission-v1/admission.json --admission crossfile=.tmp/real-defects/crossfile-admission-v2/admission.json --admission expansion=.tmp/real-defects/expansion-admission-v1/admission.json --output .tmp/real-defects/staged-shared-replay-v1-rerun
```

移除 `--validate-only` 正式运行，使用不存在的新目录。脚本每个任务只定位一次，两条分支使用同一检查点，并检查该文件在分支执行期间没有变化。定位失败时保留两条 blocked_by_localization 记录，不筛掉失败任务；取消则保持实验未完成。

每个任务的两条分支仍会各自独立做父进程评分，公开 Controls 通过不等于修复成功。检查点中不包含隐藏 Target、参考补丁或上游答案位置。旧历史试跑不并入本轮。

## 本轮结果

已完整完成 7 次共享定位、14 次独立补丁分支。7/7 个配对的检查点、候选池、非证据补丁指令、阶段预算、源码副本哈希和配置均一致；evidence_hash 在 7/7 个配对中不同。运行前后模型摘要、实现版本及准入检查也核对一致。

定位全部保持源码不变，没有定位失败或被阻塞分支；14 个补丁 Worker 均正常完成，每条仅一次实际模型调用，没有重新定位。无 API 错误、超时、全任务预算停止、越界修改或未知用量。

| 指标 | read-first | seed-first |
| --- | ---: | ---: |
| 独立验收通过 | 2/7 | 0/7 |
| 公开正常行为检查通过 | 5/7 | 7/7 |
| 实际补丁调用 | 7 | 7 |
| 实际补丁 Token | 19,660 | 20,610 |
| 加入共享定位的流水线等效 Token | 82,973 | 83,923 |

| 任务 | 共享定位 Token | read-first | seed-first |
| --- | ---: | --- | --- |
| click-help-eagerness | 10,694 | 失败 | 失败 |
| click-flag-default-map | 6,742 | 通过 | 失败 |
| click-resource-exception | 11,540 | 失败 | 失败 |
| click-flag-envvar（跨文件） | 8,085 | 失败 | 失败 |
| click-prompt-suffix | 11,686 | 失败 | 失败 |
| click-invoke-missing | 7,743 | 通过 | 失败 |
| click-shared-default | 6,823 | 失败 | 失败 |

共享定位实际调用 18 次，消耗 63,313 Token；两个补丁策略合计调用 14 次，消耗 40,270 Token。因此本轮实际合计为 **32 次模型调用、103,583 Token**。两条流水线等效总和为 166,896 Token，多出的 63,313 是重复纳入的共享定位成本，不能当成实际消费。

原始产物：`.tmp/real-defects/staged-shared-replay-v1/experiment.json`、`analysis.json` 和各次独立评分目录；每个定位目录含检查点，每个补丁目录含 Trace 和候选补丁。它们被 Git 忽略，应另行保存；本文保留统计摘要。

## 决策与局限

保留 read-first 默认，seed-first 仅作实验选项。本轮排除了上轮的候选池不一致问题，但共享证据后仍未观察到 seed-first 的修复收益；它的正常行为检查全部通过，也不能替代缺陷验收。跨文件任务在两种策略下均未通过。

本轮每个策略只有一次补丁调用；即使配置 temperature=0，也不能从单次结果推断稳定因果或泛化效果。优先级改变的是模型收到的证据内容、顺序及相关元数据，本轮不区分这些子效应。正常行为回归仅覆盖已发布 Controls，不是完整上游套件；七个缺陷仍全部是开发集。

后续已完成同一批检查点的三轮补丁复验：read-first 6/21、seed-first 0/21，同一任务及策略的重复输入与输出完全一致。详见 [固定检查点的补丁三轮复验](staged-shared-repeat-v1.md)，该批 42 次与本文 14 次分别记账。下一步转向公开需求对应的证据覆盖诊断，不继续重复同一输入，不提高预算，也不按隐藏用例逐条改提示。

## 验证

共享重放及相关测试 35 passed，全量测试 600 passed、1 skipped，改动文件 Ruff 通过。测试覆盖独立副本、CRLF、候选池及指令一致性、单次补丁调用、共享成本不重复计费，以及源码/任务/配置/检查点/证据/成本变化时在模型调用前拒绝。
