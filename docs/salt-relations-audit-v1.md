# 盐值关系检查与离线变异验证 v1

本轮完成 none-salt 的公开关系矩阵和检查 v2：人工正例通过全部 11 项测试方法，6 种人工错误变异和上轮 6 个失败补丁均被拒绝。**模型调用为 0，尚未证明模型修复率改善，也没有修复运行中的默认 Agent。**

## 约束是什么

| 构造参数 | 方法级 salt | 应采用的盐值 |
| --- | --- | --- |
| 省略 | 省略或 None | 原始 Serializer 默认盐值 |
| 显式 None | 省略或 None | 原始 Signer 默认盐值 |
| 显式字符串/字节，含空字节 | 省略或 None | 实例盐值 |
| 任意 | 显式字符串/字节，含空字节 | 方法级覆盖值 |

前两行与显式盐值保留来自公开缺陷描述；方法级覆盖来自原始 make_signer/iter_unsigners/dumps/loads 参数转发行为，是兼容性检查，不声称公开缺陷描述已经逐字规定它。原始两个构造函数的默认值从 AST 字面量读取并记录文件哈希，不读取参考补丁来确定答案。

这是人工整理的可读矩阵，尚未接入模型输入，也不是通用契约提取或自动测试生成。来源、原文位置、原始 API 哈希及逐个候选结果见 [机器摘要](salt-relations-audit-v1.json)。

## 比旧检查增加了什么

旧版比较“省略参数”和“显式默认值”两个 Serializer 输出；如果候选把二者同时改错，这个相等关系仍可能通过。本版增加独立 Signer 签名对照，避免只比较两个同时被修改的 Serializer 路径。

保留旧七个场景，增加四项：

- 省略构造参数的签名必须匹配使用原始 Serializer 默认盐值的 Signer。
- 构造时显式 None 的签名必须与省略构造参数区分。
- 显式字符串、字节和空字节必须匹配对应盐值的 Signer 签名，不能只验证能往返。
- 四类构造方式与五类方法参数组成 20 组覆盖组合，验证签名、加载往返和跨实例方法级覆盖。

测试报告中的 11 是 unittest 测试方法数，子场景不是 11 个不同缺陷。共同使用 Signer 仍有共享实现盲区，不能视为独立密码学验证。

## 离线验证

使用同一个原始仓库快照、干净源码副本和冻结检查，每次验证源码及检查前后哈希。人工正确示例沿用此前的最小 Signer None 回退补丁，只用于验证测试，不提供给模型，也不作为上游参考修复。

| 输入 | 结果 |
| --- | --- |
| 原始缺陷源码 | 有效断言失败 |
| 人工正确示例 | 11/11 方法通过 |
| None 错误回退到 Serializer 默认值 | 拒绝 |
| 改变省略参数默认值 | 拒绝 |
| 把空盐值当作默认值 | 拒绝 |
| 忽略实例盐值 | 拒绝 |
| 签名时忽略方法级覆盖 | 拒绝 |
| 加载时忽略方法级覆盖 | 拒绝 |
| 上轮两策略各三次失败补丁，重放两阶段响应 | 6/6 拒绝 |

仅将明确预期成功的操作中 TypeError、ValueError、BadSignature 转为断言失败；其他执行异常仍保留。证书读取完整本地失败日志，不使用给模型的截断片段做归因。

这六个变异是人工选择的错误机制，没有计算普遍 mutation score。12 个被拒绝候选（6 变异 + 6 历史补丁）不增加真实任务数，也不是新增模型修复实验。通过正例和拒绝这些样例，不证明检查完备。

## 使用与下一步

新实现位于 `docs/experiments/salt_relations_audit_v1.py` 和 `docs/experiments/public_checks_v2/none_salt.py`；旧检查、历史评分、默认流程和冻结实验未修改。

按 [公开检查报告](repair-public-feedback-v1.md) 设置既有 Conda 环境及 D 盘临时目录，再执行（输出路径须未存在）：

```powershell
python -B -m pytest tests/test_salt_relations_audit.py tests/test_repair_forwarding_feedback.py tests/test_repair_public_feedback.py -q -p no:cacheprovider --basetemp .tmp/salt-relations-tests-user
python -B -m docs.experiments.salt_relations_audit_v1 --output .tmp/real-defects/salt-relations-audit-user
```

离线审计不调用模型，但需要 .tmp 中冻结的原始仓库、隔离 Python 环境和上轮两阶段响应；仅 clone 不能重建所有材料。正式原始证书为 `.tmp/real-defects/salt-relations-audit-v1-final/audit.json`。初版诊断产物保留，未混入本摘要。

下一步值得开展独立模型对照：两组均使用检查 v2、相同反馈源码片段和最多一次反馈；仅一组增加上述关系矩阵。保持总 Token 预算和评分协议，验证明确的参数关系能否改善 none-salt，同时继续检查盐值隔离。本轮先完成这一步所需的离线前提，没有提前宣称修复收益。

工程验收：相关回归 33 passed；Windows 全量 934 passed、2 skipped（154.17 秒）；Ruff、冻结输入哈希、49 个本地文档链接及 PowerShell 命令语法检查通过。本轮未重跑 Linux、容器或 HTTP 故障验收；没有安装依赖，新产物均在 D 盘。
