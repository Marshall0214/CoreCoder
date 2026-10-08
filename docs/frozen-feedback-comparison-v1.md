# 双重检查反馈：27 项真实模型开发对照

2026-10-08。完整跑完固定 27 项已认证开发任务，并对新增成功补丁做源码审查和独立补充检查。

## 结论

原 Target/Controls 评分为 **16/27 → 18/27**，新增 Click 资源异常与 Boltons 常量退避两项，无丢失。但 Click 新补丁跳过 `pop_context()`，产生正常行为回归；三项新增 Context 栈检查均失败。因此不采用该策略，不把两项计分增加写成可靠修复收益。

原始实验的预设数值门槛通过，原始记录保留 `development_gain_expand_validation`。补充审计发现回归后，本轮最终决策覆盖为 **停止扩大验证，保留可选验证组件，先补齐行为保持检查**。未修改历史评分或默认 Agent/API。

## 实验方法与结果

两组分别为原公开反馈和公开检查加固定预期检查。每项共享一个新生成首轮回答，严格校验两组初始请求和补丁一致；各组独立生成可选第二轮回答，最多两次调用、累计 15,000 Token、同一 Qwen digest、不启用思考、temperature=0、最多 2048 输出 Token、6000 字符源码证据。参考源码和私有检查不进入 Worker。

| 原评分指标 | 原公开反馈 | 双重检查反馈 |
|---|---:|---:|
| 任务 | 27 | 27 |
| 独立评分通过 | 16 | 18 |
| 原 Controls 通过 | 27 | 27 |
| 反馈尝试 | 14 | 14 |
| 保留修正 | 3 | 5 |
| 调用（均含共享首轮） | 41 | 41 |
| Token（均含共享首轮） | 122954 | 124706 |

实际合计 **55 次新模型调用、171496 Token**，共享首轮只计一次；不能把两列直接相加。候选 Token 增加 1752（约 1.4%）。第二组 Worker 用时不含共享首轮推理，不据此声称提速。两组都在候选选择结束后进行独立评分。

27 项来自原 30 项开发任务中认证通过的部分，不与旧 14/30 → 17/30 比较；没有对旧留出做新推理。历史样例与结果已被查看，这不是盲测。

## 新发现的漏检

`click-resource-exception` 的首轮已经将异常参数传递给 `close`，但没有返回资源的异常抑制结果。候选修正将 `Context.__exit__` 改为提前 `return self.close(...)`，解决抑制行为，同时跳过了后面的 `pop_context()`。原公开、冻结和私有检查都漏掉了 Context 栈泄漏。

新增三项检查：正常退出恢复空栈、嵌套退出恢复外层 Context、异常退出清理 Context。执行结果：

| 被检查版本 | 三项检查 |
|---|---|
| 原始源码 | 全通过 |
| 参考源码 | 全通过 |
| 对照补丁 | 全通过 |
| 候选补丁 | 3 项失败 |

这是审查新增成功后进行的事后检查，未参与本轮生成或选择，不能伪装成预先冻结评分。原计分 18 项中至少 1 项存在新回归，其余通过也不代表完整上游行为证明。冻结预期解决已有断言的预期漂移，不能弥补未编写的行为检查。

## 代码、证据与验收

- [配对执行器](experiments/frozen_feedback_compare_v1.py)：共享首轮、分别计入预算、独立第二轮、冻结输入与模型身份校验、独立评分及成本记录。
- [Context 栈补充审计](experiments/click_context_controls_v1.py)：原始/参考双版本认证，审计执行前后源码哈希校验，零模型调用。
- [配对预算测试](../tests/test_frozen_feedback_compare.py)、[机器摘要](frozen-feedback-comparison-v1.json)。
- 主实验：`.tmp/real-defects/frozen-feedback-development-v1/experiment.json`。
- 主实验 SHA256：`60ab353390e847287c6615fe71db4dc8cf2372fbeb033ba9b830249fcdd910fa`。
- 补充审计：`.tmp/real-defects/frozen-feedback-context-audit-v1/audit.json`。
- 补充审计 SHA256：`f948a67284c3f8701bc3a08a650239908b67b4b2d7fc0beff4b20e793810fc7b`。

专项 20 passed；Windows 全量 1,284 passed、4 skipped（160 秒）。全量之后新增的事后审计执行器已实际执行四版本检查，Ruff 通过。四个跳过为可选 SQLite checkpoint 模块与 Windows 符号链接限制。所有新增输出位于 D 盘，未重跑 Docker/HTTP。

```powershell
python -m pytest tests/test_frozen_feedback_compare.py tests/test_frozen_feedback.py -q
python -m docs.experiments.frozen_feedback_compare_v1 --audit .tmp/real-defects/frozen-assertion-audit-v1-certified/audit.json --admission .tmp/real-defects/expanded-admission-v2-final/admission.json --development .tmp/real-defects/public-feedback-v2-development/experiment.json --heldout .tmp/real-defects/public-feedback-heldout-v1/experiment.json --certificates .tmp/real-defects/public-feedback-v2-certification-final/certificates.json .tmp/real-defects/public-feedback-heldout-v1-certification-final/certificates.json --output .tmp/real-defects/frozen-feedback-development-rerun
```

## 下一步

将 Context 栈三项检查纳入该任务的新版本公开保持组及独立 Controls，重新认证，旧任务和结果保持冻结。再在预算内给模型完整展示退出路径，验证异常抑制与栈清理同时成立；先收尾这个已知真实回归，再决定是否扩大策略实验。本轮不继续追加提示、重复推理或扩充部署。
