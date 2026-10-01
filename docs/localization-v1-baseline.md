# localization-v1：未新增检索的开发集基线

日期：2026-10-01。由用户执行 5 个任务 × 3 次，共 15 次。本记录从原始报告、Trace、补丁和测试输出整理，未重跑测试或模型。单项 pilot 单独记录，不计入此处统计。

## 验收及运行条件

新增任务测试 16 passed（11.30 秒），完整回归 219 passed（41.96 秒）。unchanged 0/5，reference/scripted 5/5。任务和参考修复的离线验收已通过；模型基线可以失败。

```powershell
python -m evals --suite evals/fixtures/localization-v1 --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --repeat 3 --output .tmp/evals/localization-v1-baseline
```

模型与预算：qwen3.5:27b，temperature=0，reasoning_effort=none，累计 Token 30,000，单次输出 2,048，12 轮，估算上下文 16,000，Worker 180 秒，每组测试 15 秒。原生 read/glob/grep 可用，没有新增 search_code。

15 次报告均记录基点 `7e67e34e6396003c331983348bd3402bf2854137`，工作树有未提交的开发任务、测试和文档，不能将该 commit 单独当成完整可复现版本。报告中的运行实现 SHA256 均为 `8e324a7fdc49378fb0b3b613250502209bc9220a9ddf81c76f8619be34b982f4`。fixture 不包含在这个实现哈希内，数据需结合各项 fixture/manifest/grader 哈希及实际源码一起保留。提交后记录最终提交号，不因仅提交文档而重跑。

## 结果

| 任务 | 主验收成功 | 终止状态（3 次） | 平均 Token | 平均端到端秒数 |
| --- | --- | --- | --- | --- |
| artifact-routing | 0/3 | failed_verification | 12,741.3 | 33.91 |
| checkout-rounding | 0/3 | budget_exceeded | 23,799.0 | 44.30 |
| event-replay | 0/3 | failed_verification | 14,916.0 | 41.16 |
| job-deadline | 0/3 | failed_verification | 18,801.0 | 39.61 |
| pagination-cursor | 0/3 | budget_exceeded | 25,704.7 | 33.92 |

主指标为正常完成且范围、目标和回归全部通过：**0/15**。9 次正常完成但目标测试失败；6 次累计预算预检终止。15 次回归测试均通过，均无修改范围违规。

Prompt 总 Token 274,511，Completion 13,375，总计 287,886；平均每次 19,192.4。共 101 次 LLM 调用。平均端到端 38.58 秒，中位数 38.27 秒。费用没有核算，不报告为 0。样本少且加载/缓存条件未统一，不作严格延迟比较。

有 1 次候选补丁通过全部目标与回归测试：checkout-rounding 第 1 次；它仍是 budget_exceeded，主验收按冻结协议计为失败。可单列诊断指标“候选测试通过 1/15”，不能据此更改主成功率。

## Trace 支持的失败归因

| 任务 | 已观察行为 | 尚未解决的问题 |
| --- | --- | --- |
| artifact-routing | 3 次均只改 routing.py 的最高优先级选择 | 未修路径规范化；目标仍失败 |
| checkout-rounding | 3 次均修改 pricing.py 和 fees.py，随后预算终止 | 第 1 次补丁正确但未正常收尾；第 2、3 次使用 HALF_EVEN 而非契约的 HALF_UP |
| event-replay | 3 次均将 projector.py 的提前返回改为 continue | 未修租户作用域事件键；目标仍失败 |
| job-deadline | 3 次均只修 budget.py 的单次请求超时 | 未限制 retry.py 的等待时间；目标仍失败 |
| pagination-cursor | 3 次均读取全部 7 个源码模块及可见测试，未编辑 | 在探索阶段预算耗尽，两个缺陷均保留 |

15 次均没有读取 workspace/docs 中的契约文档。模型已读取缺陷源码，因此不能把所有问题都归为“找不到文件”；当前证据更支持契约证据遗漏、跨模块修复不完整及探索/收尾成本的问题。没有保存内部推理，不能断言模型内部是否已经识别某个缺陷。

event-replay 的 3 次运行都曾尝试在 bash 命令前加 cd，被固定命令约束拒绝；随后用允许命令成功运行可见测试。这是额外工具错误，但不能据此解释全部目标失败。

预算终止不代表实际已使用 30,000 Token。预检要求剩余预算容纳下一次估算输入和预留输出；本组 6 次均报 Insufficient estimated token budget for another request。不能把它解释为连接故障或上下文溢出。

## 证据、结论和下一步

原始汇总：[Markdown](../.tmp/evals/localization-v1-baseline/summary-0448bbf4ff.md)、[JSON](../.tmp/evals/localization-v1-baseline/summary-0448bbf4ff.json)。每项产物保留候选代码、独立验证、补丁与 Trace；`.tmp/` 不入 Git，需额外备份整个运行目录。

冻结本次失败结果，不提高预算、不改评分规则来获得成功。本组与简单任务 baseline-v1 分开报告；只有 5 个独立任务，不从 0/15 推断真实仓库效果。没有证明检索一定能改善结果，也没有证明模型完全无法解决这些任务。

下一步实现统一 search_code 的共同接口，首先覆盖 Python 源码和 Markdown 契约，返回文件/行号/证据，并控制证据预算。建立同 Schema、同 Prompt、同预算的控制与关键词检索实验；必要时单独增加“固定契约上下文”的诊断配置，区分证据获取与模型推理问题。该诊断不是生产能力，也不能混入检索主对照。

接口改变后重新运行共同协议基线。本次结果是开发诊断历史参考，不能直接作为检索后端唯一变量的因果对照。原生 read/glob/grep 保持一致，评测侧参考与目标测试不进入索引。用户运行测试和模型，开发者只编写代码及说明。
