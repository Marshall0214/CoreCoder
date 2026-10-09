# 剩余 18 项失败补丁审计

## 结论（2026-10-09）

审计对象是 `system-comparison-v1-rerun` 的完整流程失败项，不混入后续小试结果。
完整成绩仍为 **32/50**；本轮 **0 次模型调用、0 次缺陷测试重跑**，没有新修复成绩。

18 项并非同一种问题。原流程状态为公开验证失败 14、首次补丁失败 3、首次输出截断 1。
进一步查看生成阶段后发现：**锚点失败共 4 项、输出截断共 2 项**，其中各有一项发生在反馈轮，
所以与上述互斥的最终状态统计不同，不能相加当作更多失败任务。

| 最后一次候选/尝试的观察 | 项数 | 含义 |
| --- | ---: | --- |
| 修正候选目标失败、保持测试通过 | 8 | 可应用，但目标行为未修好 |
| 修正候选目标和保持测试均失败 | 3 | 未修好目标，同时存在正常行为回归 |
| 修正候选目标通过、保持测试失败 | 1 | 修好了目标，但破坏上下文清理，不能接受 |
| 首轮无改动、反馈补丁拒绝 | 1 | remap 不在检索片段中，回答的原文也不在文件中 |
| 首轮行为失败、反馈截断 | 1 | predicate；未得到完整修正候选 |
| 首轮锚点拒绝 | 3 | 原文有多处出现，不能唯一替换 |
| 首轮截断 | 1 | backoff；未进入行为验证 |

## 逐项证据

下面的“解释”来自公开日志与候选源码静态对照；缺失片段是否造成模型失败仍是待验证假设。
没有读取参考补丁或独立 Target/Controls 测试源码。

| 任务 | 历史划分 | 已观察事实与解释 | 后续方向 |
| --- | --- | --- | --- |
| click-usage-empty | 开发 | 两轮均输出仅换行；修改落在窄宽度分支，宽分支仍把空 args 交给 wrap_text。write_usage 已完整提供，wrap_text 未提供 | 识别实际分支；补充被调用函数的空输入行为，而非只调整换行 |
| click-help-eagerness | 开发 | 两轮均先执行 eager callback；只改排序键。源码 get_help_option 每次构造新 HelpOption，而 parse_args 使用 invocation_order.index 按对象匹配；两个函数均不在片段中 | 检查 help option 的对象生命周期与排序输入；需运行证据确认，不把“排序错误”当作唯一原因 |
| click-flag-default-map | 开发 | help 仍显示 fast；只改 get_default。未展示的 get_help_record 仍按 self.default 选择展示的 flag，而非计算所得 default_value | 补齐默认值读取→帮助渲染调用链 |
| click-resource-exception | 开发 | 修正后 Reproduce 通过，但 3 个 Preserve 测试失败；__exit__ 中 return 跳过 pop_context，close 中 return 跳过 ExitStack 重置 | 保证返回异常抑制结果的同时执行清理；不是检索不足，两个函数已展示 |
| click-flag-envvar | 开发 | false-like 值仍激活 UPPER；修改 ParamType.split_envvar_value，并追加 convert；实际 flag 消费路径未被这些修改正确改变。Option.value_from_envvar 未展示 | 跟踪原始 envvar 到 flag_value 的转换；用运行事实确定分支 |
| click-prompt-suffix | 开发 | 两轮仍输出 Count 后的空格；修正撤销 _build_prompt 改动，净差异为零。已展示 prompt 的内部 prompt_func 仍调用 f(" ") | 检查输入显示调用，不继续仅修改字符串构造器；confirm 后续路径尚未被首断言覆盖 |
| click-shared-default | 开发 | 输出空字符串而非 alpha；修改排序键，未改默认值读取/消费。Option.get_default、Parameter.consume_value 未展示 | 检查共享参数名的默认值传播；空输出可能来自调用异常，不能仅凭此断言确定根因 |
| toolz-join-unmatched | 开发 | 首轮添加未匹配输出循环且使用未定义 iteritems；修正仅改为 d.items，原有末尾循环仍在，最终同一行输出两次 | 对照完整控制流，修正重复路径；join 已完整展示 |
| boltons-remap-set | 历史留出 | 片段都是 OrderedMultiDict，未包含 remap/default_exit；首轮 edits 为空。反馈回答虚构 remap 签名，old 在输入文件出现 0 次 | 优先修检索准入：关键 API 未覆盖时不直接生成补丁；属于明确覆盖缺口，但补齐后的收益未知 |
| more-falsy-exception | 历史留出 | one/only 已展示；同一 old 在文件出现 2 次，第一编辑即违反唯一匹配 | 用函数范围或更长唯一原文消除歧义；不可声称候选语义正确，因为未执行验证 |
| more-seekable-zero | 历史留出 | peek 锚点唯一，但 __bool__ 锚点出现 2 次，整个候选未提交；目标函数均已展示 | 类/函数范围定位；不得把 staging 的部分改动当作验证过的补丁 |
| more-split-empty | 历史留出 | split_before/after/when 已展示；前两段 old 各出现 3 次 | 函数范围定位；候选还用 iterable 真值判断空输入，对迭代器未必成立，不能仅修格式就宣称解决 |
| more-range-membership | 开发 | 0.30000000000000004 仍不属于 range；两轮只改 index。未展示的 __contains__ 仍使用精确取模，也不调用 index | 按失败操作补齐魔术方法；不要用 index 的变化推断 membership 已修复 |
| more-predicate-sentinel | 开发 | 首轮只改 replace，公开测试在 locate 的 callback 中先报 TypeError；locate 已完整展示但未修改；反馈输出 2048 Token 截断 | 先区分多 API 覆盖与输出失败；本次不能归因于“locate 没检索到”，也不是最近主动诊断候选 |
| more-gray-partial-repeat | 历史留出 | 首轮 map * repeat 报错；修正消除此 TypeError，但 partial_product 目标和正常行为仍失败；重复的是相同 iterator 对象，多个位置共同消费 | 诊断状态共享/消费顺序；两个核心函数已展示，补齐片段不能直接保证解决 |
| more-reversed-values | 历史留出 | 修改反向 numeric_range 的 stop；浮点输出仍与正向结果不一致，并使整数结果遗漏 2 | 同时保持数值生成方式与端点契约；不是单一浮点容差问题 |
| more-broadcast-single-use | 历史留出 | 修正后 is_scalar 仍调用 iter(obj)，随后又 iter(obj)，仍 opened twice；变量改成 iterators 后，后文仍引用 iterables，正常行为报 NameError | 一次创建并复用 iterator，检查重命名的所有使用点；整个函数已展示 |
| boltons-backoff-zero | 历史留出 | 首轮 finish_reason=length、输出 2048 Token，被拒绝，没有可验收候选 | 单独处理冗长补丁输出；尚不能据截断回答评价修复语义 |

## 对下一步的影响

**不把“错误行与补丁未重叠”设为硬性拒绝规则。**12 个完整修正候选里，只有
broadcast 的公开失败 traceback 含仓库源码帧，其余 11 项没有这样的帧。
断言通常发生在测试文件，callback 异常也可能只留下测试回调帧。
真实修复可以发生在上游调用处，修改异常行也可能继续失败。因此单纯做行号重叠无法覆盖主要问题。

更值得优先验证的是 **按失败操作补齐上下文**，而不是继续围绕 predicate 加日志：
开发集中 default-map 的帮助渲染函数、range-membership 的 __contains__ 明确未展示，
候选均修改了另一条路径。help、envvar、shared-default 也有调用链覆盖缺口，但根因仍需定位。
prompt 的关键 f(" ") 已展示却未修，应作为“代码已可见”的对照，避免把所有失败归为检索。

建议下一轮仅在上述开发任务中比较原流程与基于公开失败操作的检索补齐，
保持同模型、两次调用、15,000 Token、五段/6000 字符预算；候选生成与验证协议不变。
先离线检查新检索能否覆盖这些函数，再决定是否做模型小试。
人工审计选定的函数可以用于分析，不得伪装为自动检索成果。
锚点拒绝是另一个独立工程问题，不能和上下文方案捆绑后把收益全部归给检索。

## 来源、版本与边界

使用 initial-staging/initial-workspace 与 feedback-staging 读取候选；最终 workspace 已回滚，
不能从回滚源码解释历史 traceback。每条仓库帧关联候选文件哈希和候选坐标，
删除范围保留零宽边界，不把其后语句误标为改动。无源码帧时明确记为空。
非法补丁锚点计数相对该轮输入；不是在部分应用后的 staging 中统计，也不推测未执行的候选表现。

审计入口：[remaining_failure_audit_v1.py](experiments/remaining_failure_audit_v1.py)。
完整机器记录及 643 个读取文件的前后哈希位于 D 盘
`.tmp/real-defects/remaining-failure-audit-v1/audit-verified.json`；冻结基线完整性检查前后通过。
提交摘要见 [remaining-failure-audit-v1.json](remaining-failure-audit-v1.json)。

18 项包括 10 个开发失败、8 个历史留出失败。历史留出失败本轮已被审计，
以后利用本次逐项诊断改进策略时，它们属于已查看样本；未来泛化评测需新建未查看任务集。
本报告是回顾性失败分析，不是盲测，不承诺每条建议都能增加修复率。

验证：新增审计测试与冻结反馈测试共 **29 passed**，新增文件 Ruff 通过。
本轮未重跑全量项目测试、真实模型、Docker 或 HTTP 服务。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
python -B -m docs.experiments.remaining_failure_audit_v1 --output .tmp/real-defects/remaining-failure-audit-v1-rerun/audit.json
python -B -m pytest tests/test_remaining_failure_audit.py tests/test_frozen_feedback.py -q --basetemp .tmp/remaining-failure-audit-tests
```
