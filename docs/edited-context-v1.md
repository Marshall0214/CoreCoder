# 已编辑函数上下文保留 v1

## 做了什么

第一轮补丁删除了 `Serializer.make_signer` 和 `Serializer.iter_unsigners` 中的参数回退分支，导致这两个方法不再匹配原转发检索规则。第二轮虽然能看到契约摘要，却没有这两个方法的完整可编辑原文。

新增 [保留策略](experiments/edited_context_v1.py)：从已通过事务保护、实际写回的补丁中记录修改函数；第二轮从当前源码重新提取完整函数，优先放入上下文，然后填入原检索结果。拒绝补丁及无变化编辑不成为必保留项。模型看到的片段与唯一匹配编辑器使用的片段一致，不使用旧版本或按行号修改。

仍限制最多五个完整函数、组合长度 6,000 字符。必保留函数缺失、重命名、歧义、相互重叠或超预算时停止，返回 `context_unavailable`，不截断函数或扩大预算。这是函数身份与证据保留机制，不是通用语义理解或修复方案生成器。

[新 Worker](experiments/edited_context_worker_v1.py) 与 [配对入口](experiments/edited_context_compare_v1.py) 独立版本化，冻结的历史模块、引擎与默认服务未修改。

## 对照与实测

六项已查看真实任务，每项两组各一次；两组均启用冻结的运行时反馈规则，仅第二轮上下文保留策略不同。固定 Qwen、关闭思考、无工具调用、相同事务保护、最多两次请求、共享 15,000 Token；输出上限 2,048。公开检查用于反馈，私有 Target/Controls 仅由父进程独立评分。六对初始提示和回答完全相同。

零模型调用重放历史第一轮候选：旧策略提供四个函数，缺少两个已编辑方法；新策略完整保留两方法，组合长度 5,891 字符。最初两份审计草稿使用的种子不符合真实反馈链，均被审计条件拒绝；正式认证使用历史 job 中的原检索种子，并重放完整反馈打包过程，只采用 `.tmp/real-defects/edited-context-audit-v1-final/audit.json`。

| 指标 | 原上下文 | 已编辑函数优先 |
| --- | --- | --- |
| 独立验收 | 5/6 | 5/6 |
| 模型请求 | 8 | 8 |
| Prompt Token | 23,717 | 23,856 |
| Completion Token | 3,489 | 3,637 |
| 总 Token | 27,206 | 27,493 |
| Worker 总秒数 | 105.17 | 112.96 |
| none-salt 两个已编辑方法完整保留 | 0/2 | 2/2 |
| none-salt 第二轮组合字符 | 5,755 | 5,891 |

共 **16 次本地 Qwen 请求、54,699 Token、0 次 DeepSeek 请求**。无预算停止、截断或事务拒绝。两组五项其他任务都通过；none-salt 两组均未通过 Target/Controls，公开最终检查均为零异常、12 个断言失败记录（包括 subtest，不是 12 个不同缺陷）。

新策略第二轮仍仅修改 Signer 与 Serializer 构造函数的 None 默认处理，补丁与原策略一致，没有恢复第一轮删掉的转发回退。Signer 目标通过，Serializer 的显式 None 区别及错误盐值隔离仍失败。证据补齐没有使模型正确理解并修改参数语义。

## 结论与下一步

**修复了反馈时丢失已编辑函数原文的问题，没有观察到最终修复率提升。** Token 增加约 1.1%，耗时仅为本次记录。小样本、单次重复、任务此前已查看，不能宣称泛化收益或优于 Codex/Claude Code。

保留为可选实验策略，不替换默认。下一步应围绕公开失败构建可核查的修复假设：区分构造参数省略、显式 None 与方法参数回退，并对应到具体函数；先离线验证诊断信息，再开展一次固定预算的语义规划对照。当前结果不支持继续仅调整检索排名来解释该失败。

## 验收与复跑

新增 **12 项**测试：成功提交与拒绝、无变化编辑、当前版本刷新、去重、歧义、缺失函数、固定长度与函数数上限、旧版本拒绝、模型/编辑器证据一致及初始提示一致。Windows 全量 **1,056 passed、2 skipped（166.94 秒）**，Ruff 通过。未重跑 Linux、Docker 或 HTTP 验收。

机器摘要：[edited-context-v1.json](edited-context-v1.json)。原始 Trace、补丁与独立评分位于 `.tmp/real-defects/edited-context-compare-v1`，不进入 Git。复跑需既有准入快照、历史公开认证、隔离 Python 与冻结模型身份；完整历史产物不随 clone 提供。输出目录必须全新。

```powershell
python -m pytest tests/test_edited_context.py -q
python -m docs.experiments.edited_context_compare_v1 --audit-only --output .tmp/real-defects/edited-context-audit-replay
python -m docs.experiments.edited_context_compare_v1 --output .tmp/real-defects/edited-context-compare-replay
```

正式对照入口校验固定路径的离线认证；上述重放审计不会覆盖原认证。更改策略实现后需要新的协议版本及认证，不能复用旧哈希。
