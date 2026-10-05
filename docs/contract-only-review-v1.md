# 契约目录与接口审查

## 目的与实现

上一阶段的审查把缺陷源码当作预期行为，并改写了引用，导致分页测试全部被拒绝。新增 `--public-check-policy contract-only`，协议为 `public-contract-feedback-v3-contract-only`；原来的 generated 与 reviewed 保留。

测试生成与补丁阶段沿用原证据。只改变审查输入和引用方式：

- 从公开描述及选中 Markdown 提取非空行，按描述优先、文档路径排序生成契约 ID，保存来源、行号和完整原文。不读取隐藏测试或参考补丁。
- 从选中 Python 文件静态提取函数/方法名、参数名、调用方式和是否具有默认值。排除实现体、默认值内容、注解、装饰器表达式、文档字符串与模块赋值；不导入或执行源码。
- 审查请求仅含契约目录、接口元数据、生成测试、测试名称和数值断言。要求根据契约判断预期，不以当前实现是否能通过为依据；异常和返回值不能仅由接口推断。
- 模型选择契约 ID，评测器解析回原始引文。未知或空 ID 不授权测试参与反馈；漏项、重复项或格式错误关闭整份审查。沿用 Decimal 数值推导校验、测试冻结和最多一次反馈。

审查输出的 `reason_code` 限定为 consistent、contradiction、missing_contract、arithmetic、units、api_mismatch，不输出自由解释或内部推演；数值表达式与原始契约引用另行保存。这是减少格式失败和输出开销的工程约束，原因码仍由模型判断。

受限计算器增加数值参数的 min/max（2–8 个参数）和单个等式写法，例如 `min(3,2)=2`。等式两侧必须都能按允许语法计算且结果相等，还需与原断言期望相等；不支持变量、任意函数、赋值、布尔比较或自然语言式推导。原有 Decimal 精度与长度/节点/数值限额继续生效。

目录最多 160 行、每行最多 2000 字符，超限记录错误，不静默截断。ID 仅在该次输入中有意义。审查输入保存在 `public-check-review-input.json`，提示哈希记录实际输入；报告中的 `resolved_contracts` 保留引用来源。

## 验证与复跑

```powershell
python -m pytest tests/test_contract_catalog.py tests/test_check_review.py tests/test_check_arithmetic.py tests/test_contract_feedback.py -q
python -m pytest tests -q
python -m evals --suite evals/fixtures/localization-v1 --mode contract-feedback --task checkout-rounding --task pagination-cursor --public-check-policy contract-only --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --evidence-order path --patch-policy contract-coverage --output .tmp/evals/contract-only-review-v1-replay
```

重点检查 `public-check-review-input.json`、`public-check-review-response.txt`、冻结测试与 `worker-result.json` 中 `accepted_tests`、`reviews`、`feedback_attempts`。最终成功由父进程的隐藏目标/原有回归测试判定。

## 解释边界

接口元数据不构成完整 API 说明：缺少默认值含义、返回类型、属性及导入别名等信息，契约不充分时应允许 uncertain。生成测试本身可能包含错误假设，移除源码实现不能证明审查正确；ID 可查也不证明引用支持该断言。

数值计算只验证模型表达式与期望的一致性，不证明公式符合契约。剔除测试会降低行为覆盖；保留数多或模型说 accept 都不能当作修复成功。generated 仍是默认策略，新模式仅供实验。

审查最多增加一次调用，与无审查流程分协议记录；不同源码版本和不同调用机会不能合并归因。临时副本仍在可信合成任务的宿主环境执行，未增加 OS 沙箱。`.tmp/` 被 Git 忽略，报告和 Trace 需另行备份。

## 初版试点记录

固定金额舍入、分页两项；Qwen `qwen3.5:27b`、temperature 0、reasoning none、每次输出 2048 Token、累计 30000 Token、上下文估计 16000、worker 180 秒、测试 15 秒，keyword K=5、深度 2、6000 字符、path 顺序、contract-coverage 修复策略。

初版允许自由解释，金额输出截断造成无效 JSON，分页输出字段不符合契约 ID schema；两项都关闭反馈，独立验收分别通过/失败，消耗 7218/6636 Token。保留报告 `.tmp/evals/contract-only-review-v1-pilot/summary-3b17eb0979.json`，源码哈希 `9b15a18c85a7574d3d2ee7eaaa1ef21e56c8180828064e8d57aee38f874a7807`。随后只将审查解释改为固定原因码，不提高预算，另存运行目录。

精简输出版报告 `.tmp/evals/contract-only-review-v1-final-pilot/summary-ede32b5c61.json`，源码哈希 `3b4da8d2b2fd6c4a6e637b538f66f0b2a802bdbb47e1219842f9d6ef6d064ee9`：金额 6 项中保留 4 项，两个错误折扣期望被算术校验拒绝；初次修复后公开检查和独立验收通过，无反馈，消耗 5948 Token。分页审查接受了 5 项行为测试，但全部因表达式语法不支持被拒绝，例如 `min(3,2)=2`；异常测试缺少公开契约被标记 uncertain。没有有效检查，关闭反馈并独立验收失败，消耗 6628 Token。

这个结果表明引用 ID 与去除实现输入修正了此前的模型误拒，但当时算术语法兼容性阻断了实际反馈。随后增加通用 min/max 和可校验等式支持；未硬编码任务答案或修改生成测试。

## 最终共同版本（2026-10-05）

61 项相关测试通过；全量 **396 passed、1 skipped**；改动的运行时和测试文件 Ruff 检查通过。报告 `.tmp/evals/contract-only-review-v1-arithmetic-pilot/summary-efbac65632.json`，共同源码哈希 `725395e48f7a9cc96475999e5f223a58b6d66e8ae2c3f8af34994dbd2acafeb0`。

| 任务 | 审查/冻结检查 | 反馈次数 | 最终公开检查 | 独立验收 | 调用数 | 总 Token | 总耗时 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| checkout-rounding | 审查 JSON 无效，无冻结检查 | 0 | 未执行 | 通过 | 3 | 6103 | 46.45 秒 |
| pagination-cursor | 审查有效，6 项中保留 5 项 | 1 | 通过 | 通过 | 4 | 9803 | 62.94 秒 |

分页五项预期不再因当前实现缺陷被模型拒绝，引用 ID 均能解析；只有缺少公开契约的非法 limit 异常检查未参与反馈。冻结检查在原始代码和初次补丁上失败，一次反馈补充了分页模块修改，最终五项公开检查、隐藏目标及原有回归均通过。审查的实际语义与执行链路恢复，但还不是多次、跨任务的收益结论。

金额审查输出出现不完整 JSON，按既定规则关闭反馈，初次修复仍独立通过。原始输出还出现超过一个等号的推导链，现有计算器仅支持单个等式，也应拒绝。没有自动补全 JSON、修改测试或把无效审查记作通过。

最终合计 2/2 独立通过、7 次调用、15906 Token、无预算终止；只有分页完成有效审查及反馈闭环。三个开发版本分别保存，不合并成绩；与旧流程比较时审查输入、格式、算术能力及调用机会均有变化，不能归因于单项检索收益。

下一步优先约束审查输出结构与表达式格式，减少无效 JSON/推导链造成的检查丢失，再冻结共同版本扩大对照。新策略保持可选；当前没有充分证据将其替代默认策略。
