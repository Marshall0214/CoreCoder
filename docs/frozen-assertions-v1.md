# 通用固定预期验证：50 项任务的离线复核

2026-10-08。将此前单任务的固定预期检查推广为可复用的版本化组件。本轮不调用模型、不生成新补丁，不修改任何历史评分。

## 实际结果

| 指标 | 结果 |
|---|---:|
| 审核任务 | 50 |
| 冻结检查认证通过 | 44（开发 27、原留出 17） |
| 排除 | 6 |
| 冻结观察值 | 114 |
| 历史候选复核 | 88（每项首轮及最终候选） |
| 拦截历史计分成功 | 1 |
| 新模型请求 | 0 |

88 个候选中，首轮历史计分成功 23 个，新冻结检查全部通过；最终历史计分成功 28 个，其中 27 个通过，1 个被拒绝。
这是既有候选的验证审计，不是新模型修复成功率，不把开发和旧留出批次拼成新的总体效果。

## 解决什么问题

旧公开检查可以在候选中动态计算 expected，再与候选的另一个输出比较。候选若把两边一起改错，仍能通过。
新组件对复现组保存公开测试的动态预期，对保持组保存原始源码在合法输入上的实际输出；验证候选时读取这些固定记录。字面量预期本来就固定，保持原断言。

复核拒绝了 `more-gray-partial-repeat` 的历史最终补丁：重复位置共享迭代器导致输出错误；原公开检查和私有评分曾计为通过。本轮通用机制重新拦截此已知假成功，未发现第二个新增的已知漏检。

## 如何保持独立

- 观察值只从原始源码和已认证的公开用例采集；参考版本仅验证新检查，不用于生成预期。
- 原始源码的保持组通过、复现组仍失败；参考版本两组通过，才能采用该任务的冻结检查。
- 私有 Target/Controls 不用于构造预期；只保留历史计分字段，不重跑或改写历史评分。
- 历史候选必须与当时评分副本哈希一致；执行前后核对源码、用例和适配器完整性。
- 按断言位置记录循环中的观察顺序和次数，新增或缺失观察也失败；保留 tuple/list、bytes、集合、字典和基础类型信息。
- 未知对象、过深或过大值、已有 teardown、保留名字冲突均不静默接受。

## 排除与局限

以下 6 项无法完整采集或通过新认证，保留诊断，不算通过：

- itsdangerous-none-salt
- boltons-remap-set
- more-range-membership
- more-range-equality
- more-reversed-values
- boltons-xfrange-descending

异常或测试准备路径可能提前退出，导致未采集全部预期；numeric_range 等自定义对象目前不支持序列化。排除不代表上游正确版本有缺陷，只说明当前冻结适配器不适用。

只有已有等值断言的观察得到增强，没有自动增加输入、自动生成测试、完整契约证明或完整上游回归。合法正常输入仍由人工公开用例选择；编写者已见历史结果，原留出在这里属于已知案例审计。
严格冻结可能拒绝允许变化的表现，因此保留原始/参考双版本认证门槛；不得将原始缺陷输出盲目当作正常行为答案。

## 工程验收与使用入口

专项 13 passed；新组件加历史冻结兼容检查 36 passed；最终 Windows 全量 1,264 passed、4 skipped（166.96 秒）。两个可选审批模块缺少 SQLite checkpoint 依赖，另两个符号链接测试受 Windows 权限限制；跳过不计通过。Ruff 与 git diff --check 通过，未重跑 Linux/Docker/真实 HTTP。

初次将文件放入 evals 导致 8 项历史引擎冻结检查失败；最终移入独立版本化适配器，旧引擎哈希和保护保持不变，已重跑全量通过。

- [通用冻结组件](experiments/frozen_assertions_v1.py)：render 生成独立 stdlib 检查，可由现有 public_check 执行。
- [完整审计执行器](experiments/frozen_assertion_audit_v1.py)：认证与历史候选复核。
- [边界测试](../tests/test_frozen_assertions.py)、[机器摘要](frozen-assertions-v1.json)。
- 正式原始结果：.tmp/real-defects/frozen-assertion-audit-v1-certified/audit.json。

```powershell
python -m pytest tests/test_frozen_assertions.py tests/test_second_repo_admission.py tests/test_validation_admission.py -q
python -m docs.experiments.frozen_assertion_audit_v1 --admission .tmp/real-defects/expanded-admission-v2-final/admission.json --development .tmp/real-defects/public-feedback-v2-development/experiment.json --heldout .tmp/real-defects/public-feedback-heldout-v1/experiment.json --certificates .tmp/real-defects/public-feedback-v2-certification-final/certificates.json .tmp/real-defects/public-feedback-heldout-v1-certification-final/certificates.json --output .tmp/real-defects/frozen-assertion-rerun
```

需要历史认证、候选快照和隔离测试解释器；输出必须不存在。本轮全部产物写入 D 盘。

## 决策与下一步

可复用的验证适配器已完成，未接入默认 Agent/API，不宣称修复率提升。下一步用认证后的冻结检查约束公开反馈补丁的保留规则，并保留异常断言及原始独立评分；先验证完整修复流程不会发布已知假成功。
已有 30 项公开检查与 14/30 → 17/30 的反馈收益已完成，不重建同一批手写检查。原留出反馈 11/20 → 13/20 包含已知假成功，仍不采用该旧策略。
