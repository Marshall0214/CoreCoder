# 公开测试期望值审查

## 问题与边界

上一阶段的金额测试错误地把 minor 单位与基点换算后的数值再放大，导致错误反馈。生成测试通过或失败都不能代替独立验收，本阶段只改进反馈输入的质量。

新增可选 `--public-check-policy reviewed`，在测试生成后、执行前、修复前进行一次独立的模型调用。审查输入仅包含公开描述、原始选中证据和生成测试，不包含补丁、执行结果、隐藏测试或参考修复。逐项记录 accept/reject/uncertain 及公开契约引用，不允许审查改写测试；只剔除未接受的方法，再冻结保留的测试。

审查引用只能来自描述和选中 Markdown；源码可帮助确认接口，但不能作为预期行为的依据。引用存在只能说明来源可查，不证明推导正确。同一个模型的两次判断可能重复同一错误。

模型调用全部沿用累计 Token、上下文和 worker 时限。旧 `generated` 默认策略保持原协议；`reviewed` 单列 `public-contract-feedback-v2-review`，最多四次调用，包括测试生成、审查、初次修复和最多一次反馈。

## 数值推导校验

对测试方法内 `assertEqual` 的第二个参数为数值字面量的断言，自动提取方法名、断言序号与原始期望。审查必须为每个数值断言给出 `numeric_proofs`，表达式仅支持数值常量、加减乘除、括号和 `round_half_up(x)`。

本地 AST 解释器使用 Decimal 计算，不使用 eval，限制表达式为 300 字符、80 个 AST 节点，中间数值绝对值不超过 1e12，精度 50 位。计算结果必须与测试期望相等；缺失推导、错误计算或不支持的表达式都不能授权该测试参与反馈。模型声称 accept 但校验失败时，分别保存 `model_verdict`、最终 verdict 与 `numeric_error`。

这是算术一致性检查：表达式、公式和单位仍由模型从公开契约推导；模型可能选错公式，或用预期值本身构造表达式。引用校验与数值一致均不等于完整语义验证。变量期望、容器期望、负数字面量的 UnaryOp 和其他断言形式尚未做数值提取；它们依赖审查判断，整体 `semantic_correctness_verified` 始终为 false。

## 复跑

```powershell
python -m pytest tests/test_check_arithmetic.py tests/test_check_review.py tests/test_contract_feedback.py -q
python -m pytest tests -q
python -m evals --suite evals/fixtures/localization-v1 --mode contract-feedback --task checkout-rounding --task pagination-cursor --public-check-policy reviewed --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --evidence-order path --patch-policy contract-coverage --output .tmp/evals/public-check-review-v1-replay
```

检查 `public-contract-generated.py`、`public-check-review-response.txt`、过滤后的 `public-contract-checks.py`，及 `worker-result.json` 的 `public_checks.reviews`。引用不成立或算术不一致时只拒绝该方法；结构错误、漏项或重复项关闭整份审查。审查无效或没有保留测试时继续初次修复，但关闭反馈。最终成绩由父进程独立测试决定。

## 开发中的试点记录

先固定金额舍入与分页两项，预算仍为 temperature 0、reasoning none、单次输出 2048 Token、累计 30000 Token、上下文估计 16000、worker 180 秒、测试 15 秒，keyword K=5、深度 2、path 顺序及 contract-coverage 修复策略。

| 版本 | 金额独立验收 | 分页独立验收 | 问题 | 报告 |
| --- | --- | --- | --- | --- |
| 仅模型审查 | 通过，8143 Token | 失败，6706 Token | 金额两项错误期望仍被接受；分页引用不成立关闭反馈 | `.tmp/evals/public-check-review-v1-pilot/summary-08d96b3515.json` |
| 增加算术，整份引用门槛 | 通过，6283 Token | 失败，6967 Token | 两项审查均因局部引用不成立整体关闭反馈 | `.tmp/evals/public-check-review-v1-final-pilot/summary-6445a9e616.json` |

金额生成代码哈希 `03f0d525d39c6e993efc5da1999c942a8af716c3b2298f35512ae26eed9aa5db` 与上一阶段相同，包含相同两个错误折扣期望。模型审查理由继续把 0.05/0.3 错写成 0.5/30，说明单纯自我复核没有解决问题。算术版的表达式把真实运算写出后，可机械识别不一致，但整份引用门槛丢弃了其他可用方法；最终改成逐项剔除。

上述源码哈希分别为 `b4468e5fba796934a7150c210a6ed47194fdf2748261705317336812ef8bd50d`、`ebad1397da5e0b55dde27919a64927dbc1b1bd0eb357cd881f9932290a17a53a`。各版单列，不修改原报告或合并计算收益。

## 最终逐项剔除版（2026-10-05）

45 项相关测试通过，全量 **380 passed、1 skipped**；修改的运行时与测试文件 Ruff 检查通过。报告 `.tmp/evals/public-check-review-v1-isolated-pilot/summary-9fbf68a7dc.json`，共同源码哈希 `bd014051ada200a377c9b6379ac42c1056dae5e3ec9b833fd2cd11e441d66f3a`。

| 任务 | 生成/保留测试数 | 剔除原因 | 反馈次数 | 独立验收 | 调用数 | 总 Token | 总耗时 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| checkout-rounding | 6/3 | 1 项算术不一致，2 项契约引文不成立 | 0 | 通过 | 3 | 6283 | 65.70 秒 |
| pagination-cursor | 6/0 | 模型拒绝 5 项；另 1 项以源码为契约依据，被引用校验拒绝 | 0 | 失败 | 3 | 6967 | 72.07 秒 |

金额两项错误期望被剔除，其中 `100 * 5 / 10000` 的实际计算为 0.05，ROUND_HALF_UP 后为 0，与测试期望 1 不符；另一项及正确的多行累加测试因引文不成立被剔除。保留测试在原始代码上失败、初次补丁后通过，没有多余反馈，隐藏目标和回归验收通过。局部引用失败不再阻断其他可用测试，但确实损失了部分有效覆盖。

分页审查无格式错误，但模型把当前源码的缺陷当成拒绝测试的理由，违反“源码只帮助确认接口”的要求。加上不成立的引用，最终未保留任何检查，关闭反馈，候选只修改查询模块，独立验收失败。**不能把所有测试被拒绝视作期望值更可靠，也不能宣称该策略提升修复成功率。**

最终合计 1/2 独立通过、6 次调用、13250 Token、无预算终止；此前无审查试点为 2/2，但版本与流程不同且每项仅一次，不能作稳定收益结论。默认继续使用 generated，reviewed 仅供实验。

下一步将审查输入中的实现细节与公开契约分开，减少把缺陷源码当作预期行为的误判，并采用已提取契约引用标识减少引文改写；之后再冻结共同版本进行同条件对照。当前的算术一致性校验保留为可复用组件，审查不足与失败记录不隐藏。

`.tmp/` 不入 Git，应独立备份原始实验记录。默认不推广到完整任务集；先验证错误测试能否被识别，再做共同版本对照。
