# 当前策略完整 50 项评测协议

用户要求：完成一轮完整测试，重新判断当前修复效果。

固定使用 system-comparison-v1-rerun/manifest.json 的全部 50 个任务，从原始源码开始，全部重新请求模型，不复用回答。采用 DeepSeek Flash 高思考，逐项串行，原预算不变：最多两次模型调用、累计 60,000 Token、单次生成最多 32,768 Token（包括思考）、65,536 上下文预算、480 秒请求及 1,200 秒 Worker 超时。所有结果与临时文件位于 D 盘。

当前 caller-fallback-context-v1 检索应用于全部任务，每次最多五个原文片段、六千字符。公开检查失败且可执行时最多反馈修正一次，未验证补丁回滚；首次输出截断仍停止。

新增精确公开 flag 契约只适用于 click-flag-envvar，运行前必须通过原始/参考源码的离线认证。其他 49 项不附加该契约。所有任务保留原公开检查、冻结保持性检查及独立评分，成功须同时满足对应检查。

初始任务池及全部上下文先离线预检，再启动模型请求。相关代码测试 50 passed。本轮启动后不根据中途结果改变策略。

运行入口：

```powershell
python -B -m docs.experiments.current_full_repair_v1 --scope full --output .tmp/real-defects/current-full-repair-v1-20261009
```

完成后使用 current_full_report_v1 核对结果完整性、调用/预算、来源 hash、实际补丁 hash 和检查不可变性；按仓库统计，通过任务 ID 与历史高思考 43/50 对齐，列出新增成功、成功丢失、失败分类、Token 与调用次数。

历史对照不同时发生，云端别名并非固定权重，且检索和 envvar 公开验证已变化；因此结果是当前配置在已知任务池上的单轮表现，不能独立归因收益或代表未知仓库效果。

完整输出：`.tmp/real-defects/current-full-repair-v1-20261009/experiment.json`。最终报告计划输出到 current-full-repair-v1-results.md/json；以 complete=true 和审计结果为完成依据，部分结果不冒充 50 项完整成绩。

## 最终结果（2026-10-09）

50/50 完成并通过审计。独立验收 43/50（86%），历史同为 43/50；新增成功 5 项、历史成功丢失 5 项，没有总通过率提升。55 次模型调用、715,766 Token，较历史 790,530 Token 下降 9.46%；Worker 累计约 40.2 分钟。无缺失用量或进程超时，全部七项失败工作区均已恢复原始源码。

新增成功：click-help-eagerness、click-flag-default-map、click-flag-envvar、click-prompt-suffix、boltons-remap-set。

历史成功丢失：click-usage-empty、click-resource-exception、click-invoke-missing、more-reverse-empty-range、more-range-equality。

七项失败中，四项涉及输出截断：shared-default 在第二轮截断，reverse-empty-range、range-membership、range-equality 在首轮截断；其余 usage-empty、resource-exception、invoke-missing 两轮均生成补丁，但仍未通过公开/冻结验证。失败分类优先记录截断，不将它归为已生成错误补丁的语义失败。

envvar 的首轮完整候选通过旧公开/冻结检查，但被新契约拒绝。第二轮修正保留并通过独立验收，两次累计 49,265 Token。这说明新契约在该项运行中有效拦截错误并触发了成功修正；不能推广为全部任务的修复率提升。

本轮最终 Controls 50/50 通过，其中失败项已经回滚，不能解释为所有被生成候选均无回归。原完整基线与本轮完整结果分别保存，不拼接两轮成功集宣称 48/50。

当前策略不整体替换默认流程。后续优先审计五项退步：三项公开验证失败检查缺失上下文或错误补丁，另两项与现存截断项一起研究输出预算；保留成功的 envvar 契约及独立通过补丁。单次历史比较存在随机性，当前不能把所有变化归因于检索策略。

完整逐项及仓库对照见 [结果报告](current-full-repair-v1-results.md)，结构化审计见 [结果数据](current-full-repair-v1-results.json)。
