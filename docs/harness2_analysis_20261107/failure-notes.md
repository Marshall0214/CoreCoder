# Harness² 50 项复跑：25 个最终失败任务审计

本报告仅读取冻结产物，不调用模型、不联网、不执行候选代码、不重跑测试。独立评分证据仅供事后分析，未发送给模型或选择器。

- 最终失败 25 项：11 项无最终补丁；12 项补丁已应用但目标未修复；2 项目标与正常行为同时失败。
- Target 失败 / Controls 通过：23 项；Target 与 Controls 同时失败：2 项；其他组合：0。
- 非空最终补丁共 15 个 Python 文件，均仅通过本审计 AST 语法解析；这不证明补丁正确。
- 25 个最终交付分支的反馈共 306 次请求：4 次 applied、297 次 rejected、5 次 provider_failed。不是全部 200 个搜索候选的统计。
- 拒绝原因：237 次 invalid_patch_schema、48 次 anchor_not_found、11 次 syntax_error、1 次 no_change。
- 最终反馈状态：14 个 feedback_round_limit，4 个 validation_blocked，5 个 local_provider_failed，2 个 ready_for_review。
- 14 个耗尽 20 轮的最终分支全部 0 次有效应用补丁。因此“给了 20 轮”不能解释为“进行了 20 次可验证修复”。

## 逐任务结果

|任务|主分类|Controls|最终反馈状态|请求/应用|独立评分证据|
|---|---|---|---|---|---|
|click-style-color-validation|无最终补丁|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-style-color-validation/post-termination/grading.json:1)|
|itsdangerous-none-salt|引入回归且目标未修复|失败|validation_blocked|1/1|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/itsdangerous-none-salt/post-termination/grading.json:1)|
|click-help-eagerness|有补丁但目标失败|通过|local_provider_failed|2/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-help-eagerness/post-termination/grading.json:1)|
|click-flag-default-map|无最终补丁|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-flag-default-map/post-termination/grading.json:1)|
|click-resource-exception|有补丁但目标失败|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-resource-exception/post-termination/grading.json:1)|
|click-flag-envvar|有补丁但目标失败|通过|ready_for_review|0/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-flag-envvar/post-termination/grading.json:1)|
|click-prompt-suffix|有补丁但目标失败|通过|ready_for_review|0/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-prompt-suffix/post-termination/grading.json:1)|
|click-invoke-missing|无最终补丁|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-invoke-missing/post-termination/grading.json:1)|
|click-shared-default|无最终补丁|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-shared-default/post-termination/grading.json:1)|
|boltons-split-zero|无最终补丁|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/boltons-split-zero/post-termination/grading.json:1)|
|boltons-chunked-bytes|无最终补丁|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/boltons-chunked-bytes/post-termination/grading.json:1)|
|boltons-remap-set|无最终补丁|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/boltons-remap-set/post-termination/grading.json:1)|
|more-falsy-exception|有补丁但目标失败|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-falsy-exception/post-termination/grading.json:1)|
|more-seekable-zero|有补丁但目标失败|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-seekable-zero/post-termination/grading.json:1)|
|more-split-empty|有补丁但目标失败|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-split-empty/post-termination/grading.json:1)|
|more-negative-range-slice|有补丁但目标失败|通过|local_provider_failed|1/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-negative-range-slice/post-termination/grading.json:1)|
|more-range-membership|无最终补丁|通过|local_provider_failed|3/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-range-membership/post-termination/grading.json:1)|
|more-range-equality|有补丁但目标失败|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-range-equality/post-termination/grading.json:1)|
|more-predicate-sentinel|有补丁但目标失败|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-predicate-sentinel/post-termination/grading.json:1)|
|more-product-repeat|引入回归且目标未修复|失败|validation_blocked|3/1|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-product-repeat/post-termination/grading.json:1)|
|more-gray-partial-repeat|有补丁但目标失败|通过|validation_blocked|4/1|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-gray-partial-repeat/post-termination/grading.json:1)|
|more-reversed-values|无最终补丁|通过|local_provider_failed|1/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-reversed-values/post-termination/grading.json:1)|
|more-broadcast-single-use|有补丁但目标失败|通过|validation_blocked|10/1|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-broadcast-single-use/post-termination/grading.json:1)|
|boltons-xfrange-descending|无最终补丁|通过|local_provider_failed|1/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/boltons-xfrange-descending/post-termination/grading.json:1)|
|boltons-backoff-zero|无最终补丁|通过|feedback_round_limit|20/0|[grading.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/boltons-backoff-zero/post-termination/grading.json:1)|

## 有代码证据的错误机制

### 1. 格式失败消耗轮数，未形成有效反馈闭环

click-style-color-validation 的第 1 次反馈输出 action/patch 包装的统一 Diff；执行接口要求顶层仅含 edits 数组，因此直接拒绝。more-range-equality 输出 action/path/content；more-falsy-exception 输出 status/changes 的完成说明。它们不是测试失败后不断改善补丁，而是多数请求未能落盘。

- click-style-color-validation: [response.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-style-color-validation/executions/issue-cc-agg1/click-style-color-validation/agg1/feedback/rounds/001/response.txt:1)；[report.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-style-color-validation/executions/issue-cc-agg1/click-style-color-validation/agg1/feedback/rounds/001/report.json:11)。
- more-range-equality: [response.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-range-equality/executions/issue-cc-agg1/more-range-equality/agg1/feedback/rounds/001/response.txt:1)；[report.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-range-equality/executions/issue-cc-agg1/more-range-equality/agg1/feedback/rounds/001/report.json:11)。
- more-falsy-exception: [response.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-falsy-exception/executions/issue-cc-agg1/more-falsy-exception/agg1/feedback/rounds/001/response.txt:1)；[report.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-falsy-exception/executions/issue-cc-agg1/more-falsy-exception/agg1/feedback/rounds/001/report.json:11)。

证据能证明格式拒绝及无修改，不能仅据此断言修复内容本来正确，也不能断言只修格式即可提高成功率。

### 2. 四个验证阻塞发生在容器入口读取阶段

四项最后一次已应用补丁的 Reproduce.stderr.txt 完全一致：python: can't open file '/runner.py': [Errno 5] Input/output error。stdout 为空，进程退出码 2。Python 尚未读取测试入口，因此不是被测库导致测试断言失败，也没有证据指向测试结果 JSON 序列化错误。

- itsdangerous-none-salt: [Reproduce.stderr.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/itsdangerous-none-salt/executions/issue-cc-agg1/itsdangerous-none-salt/agg1/feedback/rounds/001/validation/public-logs/Reproduce.stderr.txt:1)；[report.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/itsdangerous-none-salt/executions/issue-cc-agg1/itsdangerous-none-salt/agg1/feedback/rounds/001/validation/report.json:45)。
- more-product-repeat: [Reproduce.stderr.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-product-repeat/executions/issue-cc-agg1/more-product-repeat/agg1/feedback/rounds/003/validation/public-logs/Reproduce.stderr.txt:1)；[report.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-product-repeat/executions/issue-cc-agg1/more-product-repeat/agg1/feedback/rounds/003/validation/report.json:44)。
- more-gray-partial-repeat: [Reproduce.stderr.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-gray-partial-repeat/executions/issue-cc-agg1/more-gray-partial-repeat/agg1/feedback/rounds/004/validation/public-logs/Reproduce.stderr.txt:1)；[report.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-gray-partial-repeat/executions/issue-cc-agg1/more-gray-partial-repeat/agg1/feedback/rounds/004/validation/report.json:69)。
- more-broadcast-single-use: [Reproduce.stderr.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-broadcast-single-use/executions/issue-cc-agg1/more-broadcast-single-use/agg1/feedback/rounds/010/validation/public-logs/Reproduce.stderr.txt:1)；[report.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-broadcast-single-use/executions/issue-cc-agg1/more-broadcast-single-use/agg1/feedback/rounds/010/validation/report.json:44)。

执行层先把 runner 文件只读 bind mount 为 /runner.py，再 docker exec；后续从 /tmp 取 result.json 失败统一报告 sandbox_invalid_result。检查函数转抛 SandboxError，Validator 转为 blocked，反馈入口遇 blocked 停止。

- 挂载及 exec：[runner.py](D:/project_other/CoreCoder/sandbox/runner.py:132)、[runner.py](D:/project_other/CoreCoder/sandbox/runner.py:158)。
- 结果读取及异常：[runner.py](D:/project_other/CoreCoder/sandbox/runner.py:178)、[runner.py](D:/project_other/CoreCoder/sandbox/runner.py:197)。
- 传播：[checks.py](D:/project_other/CoreCoder/repairflow/checks.py:27)、[patch_validator.py](D:/project_other/CoreCoder/repairflow/patch_validator.py:238)、[feedback_repair.py](D:/project_other/CoreCoder/repairflow/feedback_repair.py:123)。

具体为何 Docker/宿主机挂载返回 EIO 尚无证据；本报告不归因为磁盘已满、权限或某种 Docker Desktop bug。可先在候选哈希不变、测试输入不变时有限重试同一公开检查，并单独记录基础设施尝试；不要给模型追加修代码请求，也不要降级到宿主机执行。

### 3. 优化后的指导写入了与源码、需求冲突的默认值

itsdangerous-none-salt 的合成指导声称 Serializer 默认 salt 是 itsdangerous.Serializer；实际原始构造函数默认值是 itsdangerous。最终补丁将构造默认值改为 None，再替换为错误的 itsdangerous.Serializer，既不满足显式 None 与 Signer 默认一致的目标，也破坏了不传参时原有签名兼容性。

- 合成指导：[job.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/itsdangerous-none-salt/executions/issue-cc-agg1/itsdangerous-none-salt/agg1/job.json:8)。
- 原始默认值：[serializer.py](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/itsdangerous-none-salt/input/src/itsdangerous/serializer.py:92)；最终错误值：[serializer.py](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/itsdangerous-none-salt/executions/issue-cc-agg1/itsdangerous-none-salt/agg1/feedback/workspace/src/itsdangerous/serializer.py:107)。
- 独立目标错误：[Target.stderr.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/itsdangerous-none-salt/executions/issue-cc-agg1/itsdangerous-none-salt/agg1/grading/grading-logs/Target.stderr.txt:10)；正常行为错误：[Controls.stderr.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/itsdangerous-none-salt/executions/issue-cc-agg1/itsdangerous-none-salt/agg1/grading/grading-logs/Controls.stderr.txt:10)。

证据支持“指导包含错误事实，最终补丁遵循该错误事实”；并不能把全过程每次模型决策都因果归结为该条指导。首先应让指导中的项目事实关联源码行/内容哈希；无证据的默认值不要升级为强制修法。

### 4. 局部方法修复遗漏同一契约的其他实现

more-falsy-exception 修改 one()，用 is not None 识别自定义假值异常，但 only() 仍保留 raise too_long or ValueError(msg)。测试覆盖 one 与 only；最终 only 遇假值异常对象仍抛出 ValueError。

- 补丁：[patch.diff](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-falsy-exception/executions/issue-cc-agg1/more-falsy-exception/agg1/grading/patch.diff:1)。
- 漏改实现：[more.py](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-falsy-exception/executions/issue-cc-agg1/more-falsy-exception/agg1/feedback/workspace/more_itertools/more.py:3694)。
- 测试与报错：[test_admission.py](D:/project_other/CoreCoder/docs/experiments/expanded_suite_v1/checks/more-falsy-exception/test_admission.py:8)、[Target.stderr.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-falsy-exception/executions/issue-cc-agg1/more-falsy-exception/agg1/grading/grading-logs/Target.stderr.txt:15)。

这提示检索/影响范围要覆盖同一参数契约的多个入口；不是简单追加一条“多检查”即可证明有效。

### 5. 修复 __eq__ 后未同步 __hash__，破坏协议不变量

more-range-equality 新增“单元素范围只比较起点”的相等规则；__hash__ 仍包含 step，导致相等的两个对象得到不同 hash。

- 新比较规则：[more.py](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-range-equality/executions/issue-cc-agg1/more-range-equality/agg1/feedback/workspace/more_itertools/more.py:2346)。
- 原哈希计算保留：[more.py](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-range-equality/executions/issue-cc-agg1/more-range-equality/agg1/feedback/workspace/more_itertools/more.py:2376)。
- 独立测试/报错：[test_admission.py](D:/project_other/CoreCoder/docs/experiments/expanded_suite_v2/checks/more-range-equality/test_admission.py:10)、[Target.stderr.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-range-equality/executions/issue-cc-agg1/more-range-equality/agg1/grading/grading-logs/Target.stderr.txt:9)。

这是跨方法协议约束缺失。后续应按语言协议关联 eq/hash、iter/next、enter/exit 等符号，再用公开可见的通用不变量检查，不把本轮隐藏断言直接放入提示词。

### 6. 迭代器复用错误未修复，反而破坏笛卡尔积枚举顺序

more-product-repeat 只去掉 reversed，并直接返回 result。iterables * repeat 仍先重复同一个单次迭代器对象，再分别 tuple 消耗它；后续池为空，目标抛 IndexError。移除 reversed 还把正常 nth_product(1, AB, CD) 从 (A,D) 改成 (B,C)。

- 原始与最终池构建：[more.py](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-product-repeat/input/more_itertools/more.py:4201)、[more.py](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-product-repeat/executions/issue-cc-agg1/more-product-repeat/agg1/feedback/workspace/more_itertools/more.py:4201)。
- 补丁：[patch.diff](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-product-repeat/executions/issue-cc-agg1/more-product-repeat/agg1/grading/patch.diff:1)；目标错误：[Target.stderr.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-product-repeat/executions/issue-cc-agg1/more-product-repeat/agg1/grading/grading-logs/Target.stderr.txt:1)；正常行为错误：[Controls.stderr.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/more-product-repeat/executions/issue-cc-agg1/more-product-repeat/agg1/grading/grading-logs/Controls.stderr.txt:9)。

应区分“缓存输入池后重复”与“重复迭代器对象再消费”，并保持混合进制下标映射约定；此处程序语义问题已被正常行为检查发现，但最后一轮公开验证先被 EIO 阻塞。

### 7. 公开检查通过并不覆盖完整需求

click-prompt-suffix 只修 prompt()，公开 Reproduce 只调用 prompt()；独立 Target 同时覆盖 confirm()，后者仍插入空格。click-flag-envvar 公开检查仅断言不是 UPPER，None 也能通过；独立目标要求精确 False 及非匹配原值，最终失败。

- prompt 的补丁：[patch.diff](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-prompt-suffix/executions/issue-cc-agg1/click-prompt-suffix/agg1/grading/patch.diff:1)；confirm 未修复的报错：[Target.stderr.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-prompt-suffix/executions/issue-cc-agg1/click-prompt-suffix/agg1/grading/grading-logs/Target.stderr.txt:10)。
- flag-envvar 的公开通过记录：[report.json](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-flag-envvar/executions/issue-cc-agg1/click-flag-envvar/dom1/feedback/validation-000/report.json:4)；精确值断言失败：[Target.stderr.txt](D:/project_other/CoreCoder/.tmp/harness2-v2-50-20261106/arms/harness2/click-flag-envvar/executions/issue-cc-agg1/click-flag-envvar/dom1/grading/grading-logs/Target.stderr.txt:17)。

这不是建议把隐藏测试反馈给模型。下一协议应在不读取隐藏答案的条件下，从公开需求独立派生入口×边界×正常行为检查，冻结后再评估。

## 优先顺序与结论边界

1. 先修反馈交互合同：确定性输出 schema、格式错误反馈与原始任务/代码事实保持一致；记录“请求数/补丁应用数/测试反馈数”三种计数。理由：当前 14 个最终失败任务耗尽 20 轮但零应用，策略收益根本没有被充分检验。修后先做存档响应离线回放及少量本地任务，不立即跑 50。
2. 同时修沙箱入口读取失败的诊断与有限重试：只重试相同候选的检查，保留原 EIO、结果缺失与真实断言失败的区别。理由：4 个已落盘修正被基础设施阻塞，且总表 errors=0 掩盖这种内部中断。

公开检查覆盖与关联协议符号是随后最有代码语义价值的方向。当前数据证明了具体阻塞和错误，不足以保证修复它们会把 25/50 提升到某个数；需要新的受控小实验验证。

本审计新增 model_calls=0；不修改原批次产物、执行代码或评分规则。
