# Harness² 三组件自主优化试验

## 固定协议

按用户要求，让官方 Harness² 核心自主修改 `systemprompt.md`、`tool_descriptions/tool_guidance.md` 与 `context_policy.json`。不人工指定指导内容，不注入此前人工诊断补丁，不提供独立测试反馈；使用本轮全新经验库。

执行前保存 [预注册](harness2_autonomous_20261104/preregistration.json)和 [原协议](harness2_autonomous_20261104/protocol.json)：同一个 Toolz 已知开发任务、本地 Qwen3.5:27b digest、thinking=false、temperature=0、20 步、6 次编辑、1200 秒、原工具权限和 Docker 评分；Token 只记账，seed 未显式设置。

完整执行并行 k=1 的 Propose–Probe–Compose：原始执行，提出/探测通用和领域策略，合成/执行最终策略，再提取经验。唯一合成策略在评分前自动采纳，不读取独立分数选择补丁，没有 selector 投票。

## 自主选择与独立结果

| 阶段 | 去重/完整符号优先/读取索引 | 实际行为 | 调用/Token | Target/Controls |
| --- | --- | --- | --- | --- |
| base1 | 关/关/关 | 重复读后停止，无补丁 | 7 / 25,600 | 0/1，1/1 |
| inv1 | 开/关/关 | 第9步读完整join，第10步生成补丁 | 10 / 49,113 | 0/1，1/1 |
| dom1 | 开/开/开 | 重复读后停止，无补丁 | 6 / 24,263 | 0/1，1/1 |
| agg1，采纳 | 开/开/开 | 第10步读完整join，第11步生成补丁 | 11 / 55,256 | 0/1，1/1 |

三个候选还分别自主改写两份指导：通用策略强调自主推进及避免重复读，领域策略加入 join 的解释，合成策略强调先搜索、读完整函数和最小修改。不是只编辑人工指定的一句 Tool Guidance。

**流程完成，但最终缺陷未修复。**合成补丁仍在 Left Join 内新增 `for key, matches in iteritems(d)`，保留原公共循环：既未修复未定义符号，又新增重复输出。独立 Target 报 NameError；Controls 通过。检查范围是自编 Target/Controls，不是完整 Toolz 或官方 SWE-bench 测试。

生成指导也有事实错误：把报错解释成 right_default 在某分支未定义，并使用实际接口没有的 how='left'；建议“收到 repeated_action_limit 后调整策略”不符合该状态会终止执行的语义。自主生成策略不等于自动验证其事实。

## 成本及经验审查

修复器合计34次调用、154,232 Token；提议/合成/经验合计4次调用、102,472 Token。全流程 **38次调用、256,704 Token**，云 API 费用为0，本机计算成本未计价。最终修复器本身约为原始单次执行的2.16倍 Token；计入全部搜索约10.03倍，没有修复收益。

官方库留存了1条置信度自报 high 的经验，认可新增分支逻辑，并声称 inv1 被拒绝、agg1 被采纳。但 k=1 只是自动采纳最终策略，没有选择器判决 inv1 错误；采纳也不代表通过测试。该经验支持的代码仍有 NameError 和重复输出。

[经验审查](harness2_autonomous_20261104/experience-review.json)标记 reject_for_reuse，保留原经验及库记录。该库仅属于本轮，没有进入默认修复器或其他任务。本轮没有新增全局自动经验准入器；这是后置审查意见，不包装为生产级记忆治理。

## 中断与恢复

四次执行及采纳完成后，经验阶段被传输上限挡住：37份文件总正文313,848字符，整文件去重后181,479字符，超过160k。空 call-004 在请求前失败，没有模型用量。

新增 [可逆文本共享](../integrations/harness2_evidence.py)：将重复的长 JSON 字符串变成可读字典引用，完整还原并比较原内容后才发送，不删证据、不提高上限。载荷降为 **96,706字符**，共享6段文本，37份文件可精确还原。

恢复仅执行经验、独立评分和发布，校验原补丁及组件哈希，**未重跑四次修复**。原始 partial [记录](harness2_autonomous_20261104/core-result.json)保留，[恢复记录](harness2_autonomous_20261104/recovery.json)单列；独立评分在反思完成后执行。四次修复使用原版本，经验使用恢复版本，归档区分原协议、恢复实现及最终仅补充源码哈希记录的版本，不伪装成首次即成功。

## 证据与复现

[Langfuse编排Trace](http://127.0.0.1:3300/project/corecoder-issues/traces/53f5ec5610503a0f35bae7e4f86dde7c)：9个普通节点关联4条修复和4条编辑/经验Trace；38个真实Generation用量核对通过，34份修复有效请求配置/变体标识核对通过。摘要不重复计Generation。

[归档清单](harness2-autonomous-20261104.json)保存协议、策略、补丁、轨迹、独立评分、经验、恢复及许可。原接入110、复盘64、去重对照147、本地基线330份证据逐文件验证未变。

按 [接入说明](harness2-integration.md)设置已有运行环境后，在新目录复跑：

```powershell
& $controller -B -m integrations.harness2 --context-policy --task toolz-join-unmatched --output .tmp/harness2-autonomous-new
```

目录已存在拒绝覆盖，不自动整轮重跑。仅固定任务已经采纳、尚未评分时允许 `--finish-existing`；按原协议恢复相应组件模式，不能通过恢复改策略、模型或评分。恢复依赖已有原任务导出与环境，不是无需准备的便携基准。

相关回归44 passed、1 skipped；Python3.12另行检查20项通过，Ruff通过。未重跑整仓测试。

**结论与后续：**一项已知任务的自主组合试验，没有重复统计或泛化结论。不能把多个组件同时变化归因为单个开关，也不与此前去重实验拼成提升曲线。完整本地成绩仍21/50，历史DeepSeek结果不变。当前问题转向源码解释、候选行为验证及经验可信性，继续扩权缺少收益依据；可信公开自检与经验准入需另立协议，尚未实现。
