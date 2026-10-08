# Click 资源修复：补齐 Context 检查并验证有界重试

2026-10-08。**检查缺口已补齐；真实模型仍未生成合格修复。** 错误候选均被拒绝，工作副本恢复起始源码。

## 本轮实际完成

新建版本化公开保持组和独立 Controls，追加正常退出、嵌套退出、异常退出三项 Context 栈检查。原始源码和参考版本均通过新增检查，上轮错误补丁的三项检查全部失败。原 Target 和公开 Reproduce 保留，用于同时要求异常参数传递、异常抑制与正常 Context 清理。

公开 Preserve 从 1 项增至 4 项；独立 Controls 从 1 项增至 4 项，Target 仍为 2 项，公开 Reproduce 仍为 1 项。认证在调用模型前完成，参考源码只用于认证，不生成预期或进入模型。新增 Controls 与公开组共享三个回归场景，是独立执行验收，不声称隐藏、独立编写或完整上游覆盖。

旧检查、候选、历史评分、冻结引擎与默认 Agent/API 均未修改。

## 真实尝试与停止结论

| 尝试 | 调用口径 | Token | 结果 |
|---|---:|---:|---|
| 新版检查下从原始源码修复 | 2 次新调用 | 5270 | 修正补丁目标通过，但三项栈检查失败；拒绝并回滚 |
| 原始源码增加 AST 执行顺序观察 | 2 次新调用 | 5420 | 未改善，拒绝并回滚 |
| 给首个失败修正再反馈实际栈失败 | 累计 3 次，其中本阶段新增 1 次 | 累计 8409，本阶段 3139 | 仍失败，拒绝并回滚 |

实际合计 **5 次新模型调用、13829 Token**。第三行继承第一行的调用及 Token 用量，不能将累计值再次相加；累计预算仍为 15,000 Token。三次调用是新协议，不能当作与两次调用机会完全相同的收益对照。

每次尝试都在认证检查下确认候选失败，最终独立 Target 失败、Controls 通过，是因为输出已恢复原始源码，不代表模型修好了缺陷。三次上限到此停止，未追加第四次请求。

第三次仅修正 `close` 中提前返回导致的重置不可达：先保存 ExitStack 返回值，重置后再返回。但仍未修改 `Context.__exit__` 的提前返回，`pop_context()` 仍被跳过，所以目标虽通过，栈保持仍失败。这是可复查的编辑位置遗漏，不能仅凭这一例归因为模型整体推理能力。

AST 执行观察只来自原始片段，说明调用后原有语句的执行顺序，不读取参考修复或私有评分；源码加观察共 3235 字符，仍在 6000 字符证据预算内。它只进入首轮，第二轮沿用既有刷新逻辑；本轮结果不支持推广这个提示策略。

## 代码与证据

- [新版认证及真实运行](experiments/click_resource_repair_v2.py)：AST 合并检查，防止覆盖旧用例；原始、参考、已知错误候选分别认证；Worker 不接收私有检查路径。
- [执行顺序观察](experiments/source_fallthrough_context_v1.py)：版本化源码事实与证据预算约束，独立失败记录。
- [可选第三次修正](experiments/verified_correction_retry_v1.py)：继承已消费的两次调用及完整已知用量，只允许一个新请求，重新双重验证，失败恢复起始源码。
- [新版检查测试](../tests/test_click_resource_repair_v2.py)、[观察测试](../tests/test_source_fallthrough_context.py)、[预算继承与回滚测试](../tests/test_verified_correction_retry.py)、[机器摘要](click-resource-checks-v2.json)。

原始结果与 SHA256：

| 文件 | SHA256 |
|---|---|
| `.tmp/real-defects/click-resource-repair-v2/repair.json` | `df88ccd1a2a1cb2603b61697d9a03fe263bae5120e48e7a9aaaf604aac65a333` |
| `.tmp/real-defects/click-resource-fallthrough-v1/repair.json` | `c6437c7d211c417511981ada0a9524b29abf397b9bcb704e7d16cdb8813b677b` |
| `.tmp/real-defects/click-resource-verified-retry-v1/repair.json` | `d0faecf52741020a5cb08df93fb6eed16db1919ed9a78e9b23dffa975a04ed4f` |

专项 24 passed（新版检查及原回滚流程）；新组件专项 21 passed；最终全量 1,305 passed、4 skipped（154.18 秒），Ruff 通过。跳过为两个可选 SQLite checkpoint 模块和两个 Windows 符号链接测试。所有新输出位于 D 盘，未重跑 Docker/HTTP。

```powershell
python -m pytest tests/test_click_resource_repair_v2.py tests/test_source_fallthrough_context.py tests/test_verified_correction_retry.py -q
python -m docs.experiments.click_resource_repair_v2 --admission .tmp/real-defects/expanded-admission-v2-final/admission.json --certificates .tmp/real-defects/public-feedback-v2-certification-final/certificates.json --frozen-audit .tmp/real-defects/frozen-assertion-audit-v1-certified/audit.json --comparison .tmp/real-defects/frozen-feedback-development-v1/experiment.json --context-audit .tmp/real-defects/frozen-feedback-context-audit-v1/audit.json --output .tmp/real-defects/click-resource-v2-rerun
```

需要既有历史输入和隔离解释器，输出必须不存在。本轮是已知单例的工程验证，不是新的总体修复率实验。

## 决策

采用新版检查作为这个任务的可选验收协议，保留已经验证的错误补丁拒绝与回滚能力；不采用执行顺序提示或三次修正作为修复效果优化。暂停追加本例提示实验，下一步应针对实际失败语句建立可验证的代码路径定位，再决定是否恢复真实对照，不能把本轮记为“已修复 Click 缺陷”。
