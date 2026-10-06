# 紧凑策略失败审计 v1

## 范围与方法

审查上一轮 `invoke-missing`、`resource-exception`、`prompt-suffix` 的两组请求与响应。入口为 `docs/experiments/staged_failure_audit_v1.py`，不读取隐藏测试、参考补丁或 `after` 源码；不调用模型、评分器或修改原始任务。已有验收状态只作结果标注，不作探针设计的答案来源。

核对完整实验 SHA、请求及证据哈希、检查点 SHA、原始源码版本。随后在临时文件中通过现有校验器重放响应，确认六个候选源码与记录的补丁一致，再对两个任务运行公开 API 探针。共六次本地探针进程，均正常结束；原始源码、检查点及上一轮产物不变。

探针直接根据公开需求中的“保留默认类型转换”和“保留正常 suffix 渲染”设计，结果仅作事后诊断，不计入留出评分或新增成功率。

## 1. invoke-missing：跳过转换导致正常行为退化

两组修改同一个可见且在原文件中唯一匹配的代码块：

- read-first 将 `UNSET` 改为 `None` 后，继续调用 `param.type_cast_value`。
- compact 在默认值为 `UNSET` 时直接将 `kwargs[param.name]` 写为 `None`，跳过转换。

公开探针创建普通 `multiple=True` 选项，在未提供值时通过 `Context.invoke` 调用：

| 源码 | 回调收到的值 | 类型 |
| --- | --- | --- |
| 原始源码 | `()` | tuple |
| read-first 补丁 | `()` | tuple |
| compact 补丁 | `None` | NoneType |

因此已证实紧凑补丁破坏了默认类型转换行为。这是一个公开的退化见证，不能据此断言它就是隐藏验收中的具体失败用例。

上下文差异也已记录：compact 未丢失 baseline 已展示的非文档行，但删除了 29 行文档字符串，并新增 56 行 decorators 片段，分段及元数据同时改变。**还不能归因于文档删除这一单独因素。**

## 2. resource-exception：把跨缺口片段重构为旧文本

compact 的第一处 `__exit__` 编辑合法。第二处 `close` 编辑的旧文本：

- 不出现在任何一个展示片段中；
- 在原始源码中匹配次数为 0；
- 只有将已删文档字符串从源码中移除、把剩余行拼接后才匹配。

因此这是**跨文档缺口的重构文本**，不能作为原文件替换锚点。模型把展示中的分段视图当成了连续源码。现有校验器拒绝整个补丁，临时重放再次确认没有部分写入；本轮没有执行被拒绝的候选修改。

处理方向是保留真实连续范围和可编辑锚点，不应允许跨缺口替换，也不应自动替模型补回遗漏文本。签名和函数体之间删除文档会增加整段替换失败的风险，这是已观察到的表达问题。

## 3. prompt-suffix：处理缺陷时破坏正常 suffix

公开需求同时要求空 suffix 不追加空格，并保留正常 suffix。探针记录输出文本与输入函数收到的提示前缀之和，用 JSON 显示空格：

| 调用 | 原始源码 | read-first | compact |
| --- | --- | --- | --- |
| prompt，空 suffix | `"Label "` | `"Label "` | `"Label"` |
| prompt，suffix=`": "` | `"Label: "` | `"Label:"` | `"Label:"` |
| confirm，空 suffix | `"Label "` | `"Label "` | `"Label"` |
| confirm，suffix=`": "` | `"Label: "` | `"Label: "` | `"Label:"` |

compact 修正了这组空 suffix 探针，却同时损坏正常 suffix 渲染；read-first 也损坏了正常 prompt，且没有修正空 suffix。两组失败都不能仅解释为代码片段缺失。

compact 相比 baseline 多展示了 confirm 的 38 行非文档范围，未丢失 baseline 的非文档行；prompt 的原有尾部缺口仍在。代码覆盖增加没有让模型正确处理条件与保留要求。

## 决策与后续实验

继续保留 read-first 默认，compact 不推广；不提高预算、不放宽旧文本可见性和唯一匹配约束，不把本轮探针直接当成答案模板加入模型提示。

后续已完成 [保留连续片段的覆盖去重](staged-containment-packing-v1.md)：严格要求单个已选片段包含候选全文，避免联合覆盖丢失连续编辑锚点。七个实际任务的新请求与原策略完全相同，因此不执行重复模型调用。下一步追溯候选获取及定义边界缺口，保持该问题与行为契约错误分开分析。

若需要进一步解释文档删除的影响，应另建受控消融，固定非文档代码及片段布局；现有结果无法回答这个因果问题。候选池缺失及完整函数读取仍需单独版本化实验。不要继续用相同输入重跑来增加样本数。

## 复现与验证

```powershell
python docs/experiments/staged_failure_audit_v1.py --experiment .tmp/real-defects/staged-compact-live-v1-r2/experiment.json --source original=.tmp/real-defects/mixed-original-admission-v1 --source expansion=.tmp/real-defects/expansion-admission-v1 --output .tmp/real-defects/staged-failure-audit-v1-rerun
python -m pytest tests/test_staged_failure_audit.py tests/test_staged_compact_live.py tests/test_staged_compact_packing.py tests/test_staged_evidence_coverage.py tests/test_staged_replay.py tests/test_staged_repair.py -q
```

输出须为新目录；需保存旧实验、分析报告、检查点及 before 源码。最终产物为 `.tmp/real-defects/staged-failure-audit-v1-final/audit.json`，保存输入与脚本哈希、逐编辑来源分类、上下文差异及探针输出；所有产物被 Git 忽略。

本轮新增 5 项测试及相关回归共 **40 passed**，Ruff 通过。测试区分原文未展示、跨文档缺口重构、编造文本和歧义匹配，覆盖 CRLF、证据差异分类及候选源码漂移拒绝。修复实现未修改，未重跑全量测试。
