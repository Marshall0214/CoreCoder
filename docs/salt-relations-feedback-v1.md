# 公开参数关系矩阵反馈 v1

本轮完成三轮真实模型对照：仅检查 v2 与检查加关系矩阵两组均为 **0/3**。增加关系矩阵没有修好 none-salt，保持独立实验，不替换默认策略。

| 指标 | checks-only | checks-and-relations |
| --- | --- | --- |
| 独立验收通过 | 0/3 | 0/3 |
| 实际模型调用 | 6 | 6 |
| 实际 Token | 24,453 | 24,864 |

本轮共 12 次新调用；关系矩阵组 Token 为对照的 1.017 倍。三个配对的初始 Prompt、初始响应和反馈前候选源码哈希一致，均无预算停止或无效补丁。各分支的公开检查与独立 Target/Controls 结果、源码/协议哈希见 [机器摘要](salt-relations-feedback-v1.json)。

## 对照方法

本轮只研究已分析的 itsdangerous-none-salt 开发任务，各策略三次全新运行。两组都使用离线认证的检查 v2、相同第一轮 Prompt、同一套候选源码转发片段和相同公开失败反馈；仅实验组的反馈 JSON 增加四行公开参数关系矩阵。

| 策略 | 反馈内容 |
| --- | --- |
| checks-only | 检查 v2 代码、公开失败输出、候选源码片段 |
| checks-and-relations | 同上，另增加构造参数/方法级参数关系矩阵 |

关系矩阵来自公开缺陷描述和原始 API 的兼容性约束，见 [离线验证](salt-relations-audit-v1.md)。它不包含参考补丁、人工正例、历史失败候选或独立评分输出。矩阵和检查哈希在运行前冻结；完整证书仅用于父进程验收，Worker 只接收四行关系。

模型固定为 Ollama qwen3.5:27b，温度 0、reasoning none、Context 16,000、单次输出 2,048。每任务共享 15,000 Token 上限、最多两次调用、一次反馈；代码片段最多五项、6,000 字符。有效公开断言失败才触发反馈；无效补丁或执行故障不会额外重试。最终评分使用干净副本中的独立 Target/Controls，未修改历史评分。

这是一个已知缺陷上的开发实验。三次重复不增加不同任务数；若出现收益，只能说明这组检查、上下文和关系表达在这个案例中有效，不能宣称普遍提高仓库级修复率。新增检查 v2 与上轮检查不同，本轮结果不能与上轮拼接为同协议配对结果。

## 复跑

按 [公开检查报告](repair-public-feedback-v1.md) 设置既有 Conda 环境、D 盘临时目录和 PYTHONPATH。执行器需要既有冻结源码、隔离评分环境和 `.tmp/real-defects/salt-relations-audit-v1-final/audit.json`；Git 不包含这些原始材料。原始证书的哈希必须与当前实现相符，离线重新跑到其他目录不会自动替换默认证书。

```powershell
python -B -m pytest tests/test_salt_relations_feedback.py tests/test_salt_relations_audit.py tests/test_repair_forwarding_feedback.py tests/test_repair_public_feedback.py -q -p no:cacheprovider --basetemp .tmp/salt-matrix-feedback-tests-user
python -B -m docs.experiments.salt_relations_feedback_v1 --output .tmp/real-defects/salt-relations-feedback-user --repeat 3
```

运行时模块：`docs/experiments/salt_relations_worker_v1.py`；独立驱动器：`docs/experiments/salt_relations_feedback_v1.py`。正式原始报告在 `.tmp/real-defects/salt-relations-feedback-v1/experiment.json`。所有新产物在 D 盘，没有安装依赖或操作已有用户服务，默认 Agent/服务保持不变。

工程验收：相关回归 41 passed；Windows 全量 942 passed、2 skipped（160.55 秒）；新增 Python 模块和测试 Ruff 通过。本轮没有重跑 Linux、容器和 HTTP 故障验收。测试确认干预仅为第二轮关系字段、矩阵变更在模型调用前拒绝、预算停止保留第一阶段、一次反馈上限和重复次数校验。

## 结论与失败归因

关系矩阵组三次均将 Serializer 构造时的显式 None 改为 Serializer 默认值，未满足 Signer 默认值关系。两组部分补丁还在被替换片段后追加重复 dumps/loads 定义，与已有定义重叠。静态诊断只计反馈新增的重复定义，排除原始源码中的 typing overload。对照组第三轮引入不存在的 `_t.str_bytes` 注解，导致模块加载 AttributeError、零项测试执行；它没有被当作断言失败或修复成功。唯一原文匹配只保证替换位置唯一，不能保证新增代码的语义或定义结构正确。

本轮无 invalid_patch 状态仅指结构化补丁成功应用；能够应用并解析，不保证模块能加载，也不等于修复成功。独立评分保持失败，重复定义作为静态诊断记录，没有事后改评分或把本轮结果改标为无效补丁。公开测试失败方法和 Controls 状态均逐次保留。

当前证据不支持继续围绕一个缺陷叠加检索和提示变体。该实验分支到此冻结；后续应先用小型人工校准任务区分输出协议、模型配置和语义修复能力的问题，再决定是否比较其他模型。不能仅凭这个已分析案例判定模型的普遍能力，也不应把人工正例当作模型成果。
