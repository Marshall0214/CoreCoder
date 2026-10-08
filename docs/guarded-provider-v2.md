# 当前冻结流程的模型对照 v2

## 结论

同一五项开发任务、相同首轮输入和修复流程，新跑 Qwen **2/5**、DeepSeek **3/5**。
DeepSeek 新增两项成功，丢失一项成功；predicate 难例两者仍失败。
这是一次模型/服务配置小对照，不是新的提示策略收益，不替换默认模型，也不改写完整 **32/50** 成绩。

| 任务 | Qwen | DeepSeek |
| --- | --- | --- |
| click-usage-empty | 失败 | 通过 |
| click-resource-exception | 失败 | 通过 |
| more-predicate-sentinel | 失败；修正回答截断 | 失败；尾部窗口语义错误 |
| itsdangerous-none-salt | 通过 | 失败；引用不存在的成员 |
| click-style-color-validation | 通过 | 通过 |

通过须同时满足 worker 正常完成、当前公开检查、冻结公开检查、独立 Target/Controls 和修改约束。
公开检查通过不等于独立验收通过。失败候选最终回滚后，两组 Controls 都为 5/5；
这不代表十个候选补丁都保持了正常行为。

## 实际做了什么

新增 [对照脚本](experiments/guarded_provider_compare_v2.py)，复用已有非思考适配器，
直接运行现行冻结的 `frozen_feedback_v1` 流程：生成唯一原文匹配补丁 → 双重公开验证 →
失败时最多修正一次 → 不合格则回滚 → 独立评分。

从已完成的 50 项实验中预选三个已知失败、两个已知成功，全部属于开发集。
两组各重新运行一次、交替顺序，未复用历史 Qwen 输出。
首轮消息五对完全一致；第二轮使用各自候选产生的失败反馈，算法一致，内容不必相同。
未加入最近的运行时轨迹或独立场景提示，也未向模型展示参考修复或独立评分测试。

相同约束：每任务最多两次请求、共 15,000 Token、单次输出上限 2,048、执行器估算上下文
16,000、任务超时 600 秒；temperature=0、top_p=1、非流式、SDK 重试为零。
每请求超时 60 秒。输入哈希、Ollama 模型身份和源码快照在运行前后校验。

- Qwen：Ollama `qwen3.5:27b`，`reasoning_effort=none`。
- DeepSeek：`deepseek-flash`，显式 `thinking.type=disabled`。别名当前映射见
  [官方文档](https://api-docs.deepseek.com/en/)，关闭思考参数见
  [官方说明](https://api-docs.deepseek.com/guides/thinking_mode/)。云端别名及服务指纹不等于固定权重摘要。

## 成本与失败证据

| 指标 | Qwen | DeepSeek |
| --- | --- | --- |
| 独立修复验收 | 2/5 | 3/5 |
| 真实模型请求 | 9 | 9 |
| Prompt Token | 24,146 | 23,920 |
| Completion Token | 6,239 | 3,235 |
| 总 Token | 30,385 | 27,155 |
| Worker 累计耗时 | 183.22 秒 | 30.70 秒 |

共 18 次新请求、57,540 Token。没有预算预检查停止、网络错误或超时。
Qwen predicate 的修正回答达到 2,048 Token 输出上限而截断；用量仍计入预算，候选未应用。
其余 17 次返回 `stop`，均未发现思考内容；没有 reasoning token 明细，不能报告其实际消耗为零。
DeepSeek 服务指纹为 `aeb56401ca74e127821c4f9126dcb669`，缓存命中 640 Token、未命中 23,280。
不同分词器、缓存和本地/云服务条件使 Token 与耗时不能直接解释为稳定能力或价格优势。

具体失败：

- Qwen 资源任务的修正补丁解决了异常传播复现，却没有正确退出 Context 栈；普通退出、异常退出、
  嵌套退出三项公开保持检查失败。它通过冻结检查，仍被新增的保持检查拒绝。
- DeepSeek predicate 修正补丁仍忽略短尾部窗口，记录的最后一次 predicate 参数为 `(3, 4)`，
  公开测试要求 `(4,)`。回答完整和补丁能执行均未解决语义。
- DeepSeek none-salt 补丁引用未定义的 `self.default_salt`，构造 `Signer` 抛出 `AttributeError`。
  验证器捕获并回滚；Qwen 此项通过。

因此换模型能解决部分失败，却不是普遍修复方法。本轮不足以证明任一模型全面更好，
也不能将 3/5 写成 50 项结果或与旧 [5/6 对照](provider-compare-v1.md) 串成提升曲线。

## 验收、复跑与下一步

新增配置副本、密钥脱敏、异常回滚及统计测试；适配器与新入口合计 **18 passed**。
Windows 全量 **1342 passed、4 skipped（173.57 秒）**，相关 Ruff 通过；五对首轮消息、
全部冻结来源哈希与实验输出密钥扫描通过。未重跑 Docker/HTTP，未更改默认 Agent/API。

机器摘要：[guarded-provider-v2.json](guarded-provider-v2.json)。原始记录位于
`.tmp/real-defects/guarded-provider-v2-pilot`，全部写入 D 盘。
真实复跑依赖原 50 项准入快照、已认证公开检查、独立评分环境、冻结 Ollama 模型及本地 DeepSeek 密钥；
必须使用新的输出目录。单元测试不需要联网或真实密钥。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
python -B -m docs.experiments.guarded_provider_compare_v2 --output .tmp/real-defects/guarded-provider-v2-rerun
```

**本轮收尾，不自动扩大 API 调用。**下一轮可比较“首轮 + 反馈修正”与“两个独立候选 +
相同验证器筛选”：保持同模型、总调用数和 Token 预算，验证器只能使用公开认证检查选择候选，
独立评分留到最后。先在开发难例和成功回归上小对照；有净收益再扩跑，避免通过增加预算制造提升。
