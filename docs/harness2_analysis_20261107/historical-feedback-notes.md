# 历史公开反馈链审计：错误不只存在于新 Harness²

只读检查历史 `D:/project_other/CoreCoder/.tmp/harness2-vs-control-50-20261105` 和当前 `D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106` 的全部可用候选公开反馈收据及 stderr；没有模型调用或测试重跑。

可复算：`historical_feedback_audit.py`；完整逐候选记录、stderr 原文/哈希及缺失清单：`historical-feedback-audit.json`。

## 一、三个执行臂的实际反馈状态

| 数据来源 | 预期候选 | 有报告 | 初始即公开通过 | 验证阻塞 | 本地模型服务失败 | 反馈轮数耗尽 | 任务超时 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 历史原始 Agent | 50 | 50 | 22 | 11 | 7 | 10 | 0 |
| 历史 Harness² | 200 | 190 | 93 | 24 | 31 | 42 | 0 |
| 本轮 Harness² | 200 | 200 | 87 | 36 | 30 | 46 | 1 |

上述三组的所有 `ready_for_review` 候选，`feedback_rounds_attempted` 均为 0。即公开通过发生在首次验证，不是修正后通过。

| 数据来源 | 反馈尝试次数 | 补丁应用次数 | /runner.py I/O 阻塞数 | invalid_patch_schema 次数 |
|---|---:|---:|---:|---:|
| 历史原始 Agent | 265 | 11 | 11 | 150 |
| 历史 Harness² | 1091 | 24 | 24 | 838 |
| 本轮 Harness² | 1181 | 35 | 35 | 839 |

三组中每个成功应用了第一个反馈补丁的候选，随后的公开验证均遇到 `/runner.py` 的 I/O 错误，终态为 validation_blocked。没有任何反馈补丁完成了“应用后公开测试通过”的链路。这强烈说明反馈应用后的验证路径存在系统性工程缺陷；仅凭这些收据不能断言具体代码根因或修复后的修复率。

当前 36 个 blocked 中，35 个是该 I/O 错误；另外一个为 click-prompt-suffix/dom1 的初始测试挂起/超时，不能把所有 blocked 都混为同一根因。三组 blocked 的 stderr 均存在，无缺失日志。

## 二、原始控制组也已经有完全相同的错误

原始控制组以下 11 项 validation_blocked，反馈补丁应用次数均为 1：

- itsdangerous-none-salt（尝试 1 次，独立未通过）
- itsdangerous-malformed-time（1 次，独立通过）
- click-shared-default（4 次，独立未通过）
- toolz-join-unmatched（1 次，独立通过）
- more-split-empty（8 次，独立未通过）
- more-negative-range-slice（6 次，独立未通过）
- more-combination-size（4 次，独立通过）
- more-permutation-exception（4 次，独立未通过）
- more-product-repeat（3 次，独立未通过）
- more-gray-partial-repeat（3 次，独立未通过）
- more-broadcast-single-use（4 次，独立未通过）

11 份 stderr 内容完全相同：

```text
python: can't open file '/runner.py': [Errno 5] Input/output error
```

直接证据示例：

`D:/project_other/CoreCoder/.tmp/harness2-vs-control-50-20261105/arms/no_harness/itsdangerous-none-salt/executions/control/itsdangerous-none-salt/base1/feedback/rounds/001/validation/public-logs/Reproduce.stderr.txt:1`

同目录的 `Reproduce-sandbox.json` 记录退出码 2、`sandbox_status=sandbox_invalid_result`；上层 `report.json` 为 `status=blocked`、`public_checks=null`、`infrastructure_error=SandboxError: sandbox_invalid_result`。这不是业务测试产生断言失败，也不能当成“已经给模型完整测试错误，它仍修不好”。

## 三、原始控制组也有大量补丁 schema 失败

原始控制的 265 次反馈中记录：invalid_patch_schema 150 次、anchor_not_found 71 次、no_change 9 次、syntax_error 17 次、实际 applied 11 次，另 7 次本地 provider 失败；计数正好合计 265。

精确字符串 `invalid_schema` 在本次所审计的 blocked stderr 中未出现。这里存在的是补丁接口的 `invalid_patch_schema`，不要把它和 sandbox_invalid_result、策略编辑器 JSON 校验错误混成一种错误。

历史 H 补丁错误：invalid_patch_schema 838、anchor_not_found 133、anchor_ambiguous 1、no_change 18、syntax_error 46；本轮 H 分别为 839、193、1、17、65。

## 四、历史 H 缺失报告的准确口径

历史 H 有 190 份 feedback/report.json，而不是完整 200 份。缺失的 10 个候选均属于已记录的 6 项外层 error：

- click-style-color-validation：agg1
- click-help-eagerness：inv1、dom1、agg1
- click-flag-default-map：agg1
- click-invoke-missing：agg1
- boltons-remap-set：agg1
- more-range-equality：inv1、dom1、agg1

它们没有反馈终态报告，不能归类为 ready、被评分失败或成功修复。全部缺失明细保存在 JSON。原始控制 50 份和本轮 H 200 份齐全。

## 五、对比较结果的影响

24/50 和 25/50 仍然是原协议下已产生的独立评分记录，应保留；但它们比较的是共享上述缺陷的旧执行机制，不能证明“健康的 20 轮公开反馈修正入口”里 Harness² 的真实效益。

修复这个共享反馈执行路径会改变原始 Agent 和 Harness² 两条路径。若后续要评价修复后的两者质量差异，原始 24/50 就不能继续作为同机制的对照：需要至少重新核验受影响的控制任务；要报告完整 50 项同版本对照，最好两臂都冻结后重跑，不能只修新 H 再直接声称对旧 24/50 的策略提升。

先对一个过去在应用后必现 I/O 的保存补丁做不含模型的公开验证回放，可以确认执行修复；再少量真实反馈验收，最后决定是否值得完整重跑。此次审计没有开展回放或重新评分。
