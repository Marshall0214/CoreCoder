# 修复率超过 75%：思考配置对照

**最新完整结果（2026-10-09）：**同预算100次重跑完成，无思考28/50→高思考43/50（56%→86%），新增15、无丢失，Token增加263.03%。固定50项目标已达到；单轮已知任务池结果，不代表通用修复率。见 [完整报告](reasoning-budget-v1-full-rerun-20261009.md)。下文保留此前阶段记录。


更新：2026-10-09。本轮重新启动核心修复优化；此前收尾文档描述上一阶段，不能视为当前停止指令。

## 目标与验收

固定现有 50 项任务和独立评分，通过至少 38/50（76%），才满足超过 75% 的目标。当前已验证成绩仍为 32/50；本轮尚未完成，不宣称提升。

不移除难题、不放宽目标或正常行为检查、不把人工诊断补丁放入模型输入、不将开发集或多策略逐题择优的并集当作全量成绩。任务已被分析，成绩不是全新盲测；后续泛化仍需新任务。

## 为什么先试这个

最近多个案例已经提供相关源码与公开测试，但模型仍生成错误逻辑；继续叠加运行信息没有净提升。先比较 Qwen 原生思考开关，检验模型推理配置是否是可改善的瓶颈，而不是继续对单题定制提示。此前 thinking 的人工任务校准不能证明真实缺陷收益。

Ollama 原生接口提供 think 参数和独立 thinking 字段，见 [官方文档](https://github.com/ollama/ollama/blob/main/docs/capabilities/thinking.mdx)。适配器只记录思考存在性/字符数，不持久化思考内容；使用返回的全部生成 Token 计费到任务预算，没有独立思考 Token 分项统计。

## 协议

- 两组均 Qwen3.5:27b，原生 `/api/chat`，同一模型摘要、temperature=0、top_p=1、seed=17。
- 两组仅 think=false/true 不同；首轮描述、证据和补丁协议相同。反馈来自各自候选的相同公开验证流程。
- 固定冻结反馈工作流，最多两次模型调用，每任务 15,000 Token 总预算、16,000 上下文、600 秒。
- 两组均最大生成 8,192 Token，按剩余预算预留；思考消耗生成空间。与历史 2,048 输出上限和 OpenAI 兼容接口不同，历史差异不能全归因于思考。
- 初始运行可行性检查为两个已知开发失败；随后开发集 30 项配对，不只比较失败项。完整 50 项以同一策略新跑，禁止复用局部成功凑总分。
- 顺序交替、全新请求、独立工作区；全部失败、截断、超时和使用量保留，独立评分位于 Worker 外。

若开发集有净成功增长且无使用量缺失，继续完整测试；否则根据失败分布调整候选模型或输出策略，再单独记录新协议。达到目标也必须说明成本与回归，不能承诺提前达到。

## 代码与运行入口

- [原生适配器](experiments/reasoning_provider_v1.py)
- [配对执行器](experiments/reasoning_repair_compare_v1.py)
- [使用量与响应校验测试](../tests/test_reasoning_provider.py)

所有实验输出、缓存和临时目录写入 D 盘；不安装新模型或使用 DeepSeek。

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp'
$env:TMP = $env:TEMP
python -B -m docs.experiments.reasoning_repair_compare_v1 --scope pilot --output .tmp/real-defects/reasoning-repair-v1-pilot-new
python -B -m docs.experiments.reasoning_repair_compare_v1 --scope development --output .tmp/real-defects/reasoning-repair-v1-development-new
```

每次使用新的输出目录。正在运行的冻结代码不能修改；结果保存在各自 `experiment.json`，只有 `complete=true` 才能视为运行完成。

## 首轮已观察到的问题

零温度思考组的两个初始请求均达到 8,192 生成 Token 后截断，没有最终补丁，2/2 失败；不是目标测试给出的语义判定。第一项记录思考 40,097 字符，内容为空，返回用量完整；全部消耗计入成本。首轮已完整结束，无思考与思考组均 0/2；两个已知失败不是全量成绩。逐项结果见 [首轮 JSON](reasoning-repair-v1-pilot.json)。

查阅 [Qwen3.5-27B 官方模型卡](https://huggingface.co/Qwen/Qwen3.5-27B) 后发现，精确编码思考推荐 temperature=0.6、top_p=0.95、top_k=20、min_p=0、presence_penalty=0、repetition_penalty=1。零温度配置不符合该推荐；思考截断不能归因为模型本身完全无效。官方也建议更长输出，但本阶段优先检验既定总预算下的可用配置，不偷偷放宽成本上限。

另建 [v2 适配器](experiments/reasoning_provider_v2.py) 与 [v2 执行器](experiments/reasoning_repair_compare_v2.py)，两组均使用上述编码采样（Ollama 参数名为 repeat_penalty），think 仍为唯一组间差异；预算、上下文与独立评分保持一致。与历史结果相比还改变采样，不能全部归因于 think。先 pilot 可行性检查，再决定开发集执行。

当前代码验收：v1 增加后完整 **1424 passed、4 skipped（163.51 秒）**；v2 增加后聚焦 **27 passed**，两版 Ruff 均通过。完整回归未覆盖后加入的 v2 文件，v2 的使用量、采样参数及失败拒绝由聚焦测试覆盖。

## 采样配置的扩大验证

推荐编码采样的小试首题 click-usage-empty：无思考组独立验收通过（2 次调用、7,003 Token），思考组仍在生成上限截断。两题小试已结束：无思考 1/2（4 调用、13,845 Token、47.40 秒），思考 0/2（3 调用、21,986 Token、277.87 秒）。第二题两组均公开验证失败；思考首题截断。逐项数据见 [v2 小试 JSON](reasoning-repair-v2-pilot.json)。不把局部成功当成任务池提升。

准备 [固定采样执行器](experiments/sampled_repair_evaluation_v1.py)，复用经过测试的 v2 Worker，对开发集或完整集使用统一无思考配置。优先无思考是基于可交付完整补丁与较低耗时的当前证据，不按具体任务动态挑选 think 开关；开发集若退步则不推广。

```powershell
python -B -m docs.experiments.sampled_repair_evaluation_v1 --scope development --output .tmp/real-defects/sampled-repair-v1-development-new
```

该候选与历史 32/50 相比同时变化原生接口、采样及输出上限；最多两次调用与 15,000 Token 总上限、评分、检索和反馈逻辑不变。开发集需要比较通过集合和成本，而不只看通过总数。新执行器 Ruff 通过，复用 Worker 聚焦回归 27 passed。

开发集执行已启动：`.tmp/real-defects/sampled-repair-v1-development/experiment.json`。全部 30 项从原始源码新跑，不拼接小试成功；现已完成但效果下降，完整历史成绩仍为 32/50。

## 开发集结论与后续模型验证

本地推荐采样无思考开发集已经完整结束：冻结流程 20/30，新配置 17/30，新增 click-usage-empty、toolz-join-unmatched，丢失 boltons-chunked-bytes、click-invoke-missing、click-style-color-validation、itsdangerous-malformed-time、itsdangerous-none-salt；净减少 3 项，**不采用、不扩大到完整集**。45 次调用、134,457 Token，缺失用量 0。结果核对见 [开发集审计](sampled-repair-v1-development.json)。原始运行 complete=true，冻结输入及历史基线哈希已核对。

DeepSeek Flash 使用既有配置与凭据，新增 JSON 输出、生成上限按剩余预算调整，模型变化与生成策略需作为整体报告：

- [低强度思考适配器](experiments/deepseek_reasoning_provider_v1.py)、[小试执行器](experiments/deepseek_reasoning_repair_v1.py)：15,000 总预算、8,192 生成上限。两题 1/2；Usage 首轮通过，predicate 初始输出截断。见 [逐项记录](deepseek-reasoning-v1-pilot.json)。
- [无思考适配器](experiments/deepseek_direct_provider_v1.py)、[开发集执行器](experiments/deepseek_direct_repair_v1.py)：仍最多两次调用、15,000 总预算、8,192 输出，完整开发集已结束 22/30，对照历史 20/30：新增 Usage、join、range-membership、predicate-sentinel；丢失 none-salt、chunked-bytes，净增加 2。44 次调用、121,839 Token，缺失用量 0。见 [开发集核对](deepseek-direct-v1-development.json)。已启动完整 50 项全新运行，尚未完成。
- [扩大预算思考执行器](experiments/deepseek_reasoning_repair_v2.py)：明确改为每任务 30,000 总 Token、最多 24,576 生成 Token、32,768 上下文、900 秒，最多两次调用不变。先运行相同两题，确认足够推理空间是否可产生可验证补丁。即使提高成功数，也不能描述为同成本收益，不改写原始 32/50。

官方说明见 [DeepSeek 思考接口](https://api-docs.deepseek.com/guides/thinking_mode/)。未将参考补丁、人工诊断补丁或独立评分测试发给云模型；只发送与本地实验相同的公共仓库证据及公开失败反馈。记录返回的 reasoning token 明细（有则记录），不持久化思考文本。模型别名没有可核对的云端权重摘要，保存返回 fingerprint 供追踪。

新增 [完整试验核对器](experiments/repair_trial_report_v1.py) 检查任务覆盖、重复结果和 accepted 与验证记录一致性，并统计 gained/lost；开发集即使全通过，也不标记 50 项目标达到。

本轮代码回归：完整 1436 passed、4 skipped（168.38 秒），覆盖核对器及低强度思考适配器；后加入的无思考适配器与核对修正聚焦 8 passed / 5 passed，Ruff 通过。全量回归未包括后加入的文件，不混报为全部覆盖。

扩大预算思考小试已完成，仍 1/2：Usage 通过，predicate 已返回完整候选但公开语义验收失败。见 [扩大预算小试](deepseek-reasoning-v2-pilot.json)。增加输出空间消除了本次截断，却未修好目标语义，不扩大该策略。

当前正在运行完整 DeepSeek 无思考试验：`.tmp/real-defects/deepseek-direct-v1-full/experiment.json`。仍需全部 50 项新跑并核对，才能判定 38/50 目标；不以开发集或历史留出成绩拼接结论。默认 CoreCoder Agent/API 暂未切换模型或实验工作流。

完整 DeepSeek 无思考试验已结束并核对：33/50（66%），较历史 32/50 新增 6、丢失 5，净增 1；70 调用、195,101 Token。开发集通过的 range-membership、predicate 在全量新跑中再次失败，不拼接开发集成功。见 [全量核对](deepseek-direct-v1-full.json)。目标尚未达到；当前转向 [连续修正配对](bounded-repair-v1.md)。上文运行中状态保留为历史记录。


最新后续：连续重试配对21/30 → 20/30，不推广；模型选取源码对照20/30 → 19/30、Token增加42.9%，同样不推广。见 [选取实验](selected-source-v1.md)。最佳完整已验证成绩仍33/50，目标38/50未达到。
