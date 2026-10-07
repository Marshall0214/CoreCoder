# 公开检查驱动的修复假设实验

## 本轮实现

上一轮已补回第一轮编辑方法的完整原文，但模型仍混淆构造参数、省略值与方法参数回退。本轮在已有第二次请求中，增加简短的结构化修复假设，格式为 `hypotheses + edits`：每条声明关联公开测试与已提供的完整函数，再给出唯一文本匹配补丁。

当前 [假设校验器 v2](experiments/repair_hypothesis_v2.py) 完成三件事：

1. 从认证公开检查的 AST 和结构化失败记录提取测试身份，将 subtest 合并为方法；最多指定五个失败方法，记录其余未指定数量。提供其他公开测试名称，不能把这些名称理解为“已经通过”。
2. 写回前验证 JSON、真实测试引用、实际显示的函数引用、指定失败覆盖及编辑原文与引用函数的关系。不读取私有评分，也不通过硬编码任务名称生成修复答案。
3. 执行公开检查后，把每条假设标记为 `supported_on_public_checks`、`failed_public_checks` 或 `unverified`。支持仅指引用的公开测试通过，不证明声明文字、函数归因或完整程序正确。

[Worker v2](experiments/repair_hypothesis_worker_v2.py) 仅在公开行为反馈时启用新格式，初始请求和事务拒绝反馈保持原样；最多两次调用，共享 15,000 Token，输出上限 2,048。两组都保留已编辑函数当前版本，使用相同 6,000 字符与五函数上限、固定 Qwen、关闭思考、无工具调用及独立 Target/Controls。冻结引擎和默认服务未修改。

## 离线验收

零模型调用重放历史候选，检查诊断身份和无效引用拒绝；已有人工正确修复通过公开检查，历史语义错误补丁对应的假设被实际测试否定。这验证引用校验及结果标记机制，不是模型收益证明。

公开检查的 `public_check_sha256` 诊断字段计算的是读取并规范换行后的 UTF-8 文本；离线认证还单独记录原始文件字节哈希，两者可能不同。完整公开代码仍来自既有认证，不使用新生成测试。

## 真实对照与校验修正

初版 [v1 校验器](experiments/repair_hypothesis_v1.py) 错误地只允许引用指定失败测试，导致模型为保留行为引用现有回归测试时被拒绝。这是实现问题，已在 v2 修正：允许所有实际存在的公开测试，指定失败仍必须覆盖，未知引用仍拒绝。

| 版本与范围 | 原补丁流程 | 结构化假设流程 | 请求数 | Token：原 / 假设 |
| --- | --- | --- | --- | --- |
| v1：六项已查看任务，各一次 | 5/6 | 4/6；两次假设拒绝 | 16 | 27,513 / 28,342 |
| v2：两项会触发公开反馈的任务，各一次 | 1/2 | 0/2；均为语义验收失败 | 8 | 16,911 / 17,748 |

v1 的六对、v2 的两对初始提示和回答分别完全相同。v2 未重跑另外四项，不能汇总成“新版六项通过率”。两个版本分别保留记录，不覆盖旧结果；总成本为 **24 次本地 Qwen 请求、90,514 Token、0 次 DeepSeek 请求**。没有增加重试、预算或模型调用上限，无 Token 停止和输出截断。

v2 的局部结果：

- `click-usage-empty`：原流程通过；假设流程失败。模型声称修复宽布局，却只在另一分支添加注释与 `pass`；最终三个公开断言失败。三条假设中两条失败，一条所引回归测试通过。
- `itsdangerous-none-salt`：两组都失败。假设流程仍仅补 Signer 的 None 默认处理，没有恢复方法参数的实例盐回退；模型明确声称方法 None 应使用 Signer 默认，与公开方法矩阵相冲突。五条假设中四条失败，一条所引检查通过，最终公开检查仍有 12 个断言失败记录、零异常；独立 Target/Controls 都未通过。

这些计数是公开问题记录与假设组，不是不同缺陷数。小样本、任务已查看、每项各一次，不能作为泛化评测。

## 决策

**不采用结构化假设作为默认修复策略。** 修正引用校验后仍出现原来可修复的任务失败，且 Token 增加；现有结果不支持成功率优化。简历不增加修复收益数字。

可保留失败诊断及测试关联代码作为实验产物。它说明“引用合法、说明清晰、补丁结构合法”仍不足以保证行为正确。下一步转向执行层：在最终候选写回前运行认证公开行为检查，通过后提交；失败保留诊断并回滚，维持已有一次反馈预算。先用历史失败及正确补丁离线验证语义验收与提交关系，不继续围绕这一单例追加提示词格式。

## 验收与复跑

新增 **25 项**测试，覆盖 subtest 聚合、不完整观察、未知引用、回归测试引用、指定失败覆盖、编辑依据、校验先于事务、初始提示一致、一次反馈和累计预算，以及实际测试否定假设。专项 **25 passed（0.56 秒）**，最终 Windows 全量 **1,081 passed、2 skipped（168.99 秒）**；Ruff 通过。未重跑 Linux、Docker 或 HTTP。

机器摘要：[repair-hypothesis-v1.json](repair-hypothesis-v1.json)。初版与修正版原始记录分别在 `.tmp/real-defects/repair-hypothesis-compare-v1`、`.tmp/real-defects/repair-hypothesis-compare-v2`，不进入 Git。[v2 对照入口](experiments/repair_hypothesis_compare_v2.py) 校验固定路径的离线认证；复跑依赖既有准入快照、认证及隔离 Python。输出目录必须全新。

```powershell
python -m pytest tests/test_repair_hypothesis.py tests/test_repair_hypothesis_v2.py -q
python -m docs.experiments.repair_hypothesis_compare_v2 --audit-only --output .tmp/real-defects/repair-hypothesis-audit-replay
python -m docs.experiments.repair_hypothesis_compare_v2 --task click-usage-empty --task itsdangerous-none-salt --output .tmp/real-defects/repair-hypothesis-compare-replay
```

重放审计不覆盖正式认证；修改实现后需新的协议版本和认证，不能复用旧哈希。
