# 冻结检查接入补丁保留流程

2026-10-08。本轮将已认证的固定预期检查接入可选修复 Worker，完成生成、检查、一次反馈修正和回滚闭环。

## 解决的问题

原公开检查可能随着候选代码一起改变预期，导致错误补丁仍被计为通过。现在补丁必须同时通过原公开 Reproduce/Preserve 和固定预期检查，才保留在任务工作副本中。这里的“保留”不代表合并、部署或创建 PR。

首轮未通过且检查正常执行时，最多反馈修正一次；两次请求共享原预算。反馈包含可读公开测试与两组失败观察，不读取私有评分答案。修正失败则退回首轮候选；首轮也不合格则恢复任务起始源码。截断、预算停止、验证异常和检查篡改均不能留下待采用补丁。

## 完整离线验收

| 指标 | 结果 |
|---|---:|
| 已认证任务重放 | 44/44 |
| 保留补丁 / 独立评分通过 | 27 / 27 |
| 恢复起始源码 | 17 |
| 触发反馈 / 保留修正 | 17 / 4 |
| 拦截历史假成功 | 1：more-gray-partial-repeat |
| 缺失历史回答 / 新模型调用 | 0 / 0 |

历史评分曾计为成功的 28 项中，本流程保留 27 项并拒绝已知假成功。这是验证准确性和回滚可靠性的验收，不能写成修复率提升。历史回答未按新反馈重新推理；旧留出已成为已知案例，不是新的盲测。

独立 Target/Controls 在补丁选择结束后执行，未参与选择。它们是人工选定检查，不是完整上游回归。仅覆盖冻结检查认证通过的 44 项；另外 6 项的排除原因见 [冻结检查报告](frozen-assertions-v1.md)。

## 代码与证据

- [修复 Worker](experiments/frozen_feedback_v1.py)：原输入、源码证据和两组检查哈希校验；限制回滚目标为任务自身工作区；输出检查、保留决策与最终源码哈希。
- [完整重放执行器](experiments/frozen_feedback_replay_v1.py)：验证历史输入完整性，保留 Provider 截断状态，核对首轮源码与历史候选一致，最后独立评分。
- [专项测试](../tests/test_frozen_feedback.py)、[机器摘要](frozen-feedback-v1.json)。
- 原始结果：`.tmp/real-defects/frozen-feedback-replay-v1-accepted/replay.json`。
- 原始结果 SHA256：`948e3ad9ccad8d6bdbf8913e4d0a931781d1d8dafb752eccc8c397b4cc2e7db5`。

专项 15 passed；全量 1,277 passed、4 skipped（156.60 秒），全量收集后补充的 2 项回答重放回归用例另经专项通过。跳过为两个可选 SQLite checkpoint 模块和两个 Windows 符号链接测试。Ruff 通过。所有新输出位于 D 盘；未修改历史引擎冻结协议、默认 Agent/API，未重跑 Docker/HTTP。

```powershell
python -m pytest tests/test_frozen_feedback.py -q
python -m docs.experiments.frozen_feedback_replay_v1 --audit .tmp/real-defects/frozen-assertion-audit-v1-certified/audit.json --admission .tmp/real-defects/expanded-admission-v2-final/admission.json --development .tmp/real-defects/public-feedback-v2-development/experiment.json --heldout .tmp/real-defects/public-feedback-heldout-v1/experiment.json --certificates .tmp/real-defects/public-feedback-v2-certification-final/certificates.json .tmp/real-defects/public-feedback-heldout-v1-certification-final/certificates.json --output .tmp/real-defects/frozen-feedback-rerun
```

重放需要既有历史回答、源码、认证检查及隔离测试解释器，输出目录必须不存在。真实调用入口为 `python -m docs.experiments.frozen_feedback_v1 --worker <job.json>`，job 需含已认证检查路径和哈希、起始源码哈希、公开描述与证据；不要直接把用户源码目录作为 workspace。

## 下一步

验证和回滚闭环到此收尾。下一轮在固定开发任务、同模型同预算下重新生成回答，对比原公开反馈与双重检查反馈，统计独立修复通过数、正常行为回归、误保留、Token 和耗时。仅在真实调用显示收益后扩大验证；不继续以历史重放替代核心修复效果实验。
