# Predicate 尾部窗口：公开运行证据小试验

## 问题与假设

前一轮最小补丁提示消除了 `more-predicate-sentinel` 第二轮的输出截断，但目标仍失败：
模型过滤整个含填充值的窗口，没有满足尾部有效元素仍交给 predicate 的公开预期。
本轮只验证一个问题：提供实际输入和 predicate 调用参数，能否帮助模型修正窗口语义？

这是一个已知开发失败的诊断试验，不是新测试集或成功率提升实验。默认 Agent/API 和
完整五十项的 32/50 历史结论保持不变。

## 实现

- 在隔离子进程中执行原认证公开 Reproduce/Preserve，不改动测试或源码。
- 捕获允许源码内 `locate`/`replace` 的输入、window_size，以及直接传入的公开 Python
  predicate 的参数、返回值和异常类型。包括普通 Python lambda；不捕获内置 bool 的内部执行。
- 只序列化上述指定字段，不记录其他局部变量、环境变量或异常对象内容。非普通值标为类型
  和“未捕获”，不调用对象 repr、迭代器或自定义比较；不能据一个 object 标记断言它就是 padding。
- 每个测试最多 12 个操作，每个操作最多 16 次 predicate 调用，每个序列最多 12 个值；
  最多两层容器、字符串最多 80 字符。操作/调用记录截断或探测不可用时不加入运行证据；
  序列采样省略的值用 `omitted` 标注，不把样本描述为完整输入。
- 每组限时 15 秒；源码/公开测试哈希改变则拒绝。探测结果必须与普通公开执行的测试数量、
  成败相符，无跳过或预期失败；完整运行证据超过 5000 字符时回退原反馈。

第二轮只在原反馈中追加 `public_runtime_observations`。原 system prompt、失败日志、公开
测试代码、源码种子刷新和补丁格式都不改；不附加修改摘要或上一轮的新审查提示。
不读取独立 Target/Controls 或参考修复，也不直接给出补丁答案。

代码：[采集器](experiments/predicate_trace_probe_v1.py)、
[反馈接入](experiments/predicate_runtime_feedback_v1.py)、
[对照执行器](experiments/predicate_runtime_compare_v1.py)、[测试](../tests/test_predicate_runtime.py)。

## 配对协议

固定任务为 `more-predicate-sentinel`，两组 `unchanged-feedback` 与 `predicate-runtime`。
从已完成 `diagnostic-feedback-v1-pilot` 的原反馈组复用首轮请求、回答及用量，重新应用补丁；
严格核对首轮请求相同、候选源码哈希相同，然后各产生一次新的第二轮回答。
原失败反馈也复用同一份历史记录，先核对当前公开检查的成败、测试数量、失败/错误数量以及
公开测试代码一致，避免两组日志中的测试耗时文本不同。

历史首轮的 2922 输入 Token、137 输出 Token，仍占两组各自预算。模型预算账面最多两次，
但本轮实际只新增两次模型调用；报告分别记录预算用量与新推理用量，不将回放当新模型运行。

模型仍 qwen3.5:27b、非思考、temperature=0、top_p=1，累计上限 15000 Token，
单次输出 2048 Token、上下文 16000、单项 600 秒。只有公开运行证据是干预变量。
独立评分在 worker 退出后运行；公开/冻结公开检查、评分及失败回滚均沿用原实现。

输入源码、历史回答、实验代码、认证检查均有哈希。每项失败保留完整记录，不只统计成功。
两组顺序固定为原反馈在前；单次、小样本不能说明统计显著性或耗时收益。

## 复现

先激活 corecoder。使用新的输出目录，所有临时产物留在 D 盘：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp'
$env:TMP = $env:TEMP
python -B -m pytest tests/test_predicate_runtime.py tests/test_frozen_feedback.py -q
python -B -m docs.experiments.predicate_runtime_compare_v1 --output .tmp/real-defects/predicate-runtime-v1-new
```

正式记录：`.tmp/real-defects/predicate-runtime-v1-fixed-feedback/experiment.json`，
只有 `complete=true` 才代表两组执行与独立评分全部完成。

## 验证与结果

相关测试 23 项通过，全量 **1331 passed、4 skipped**；Ruff 通过。

初次试跑保留在 `.tmp/real-defects/predicate-runtime-v1-pilot/`：两组均失败，运行证据组
生成了完整补丁，却仍跳过整个尾部窗口。配对审计发现原日志耗时文本有 `0.000s/0.001s`
差异，因此不将该轮作为严格唯一变量对照；增加共享原反馈保护后重新运行正式两组。
初次试跑新增两次模型调用，正式对照另新增两次，总计四次，不隐藏前期消耗。

| 正式方案 | 整项通过 | 第二轮状态 | 第二轮输出 Token | 新推理 Token | 含历史首轮的预算 Token |
| --- | --- | --- | --- | --- | --- |
| unchanged-feedback | 0/1 | output_truncated | 2048 | 5525 | 8584 |
| predicate-runtime | 0/1 | completed | 248 | 4286 | 7345 |

正式两组首轮候选哈希相同；第二轮 system prompt 相同，移除新增运行证据字段后 user payload
完全相同。源码上下文、原失败日志、公开测试代码、预算和验证器没有其他差异；冻结哈希检查通过。

运行证据确实包含：输入 `[4]`、window_size=2，predicate 收到 `(4, object)`，随后抛出
TypeError。object 仅记录类型，不从这个标记直接判定其身份。模型在 locate 中将填充值改为
None 并过滤 None，候选通过了公开测试前面的 locate 断言，包括最后一次参数 `(4,)`。
但随后 `replace([2, 3, 4], …, window_size=2)` 的 predicate 仍收到填充值而抛出 TypeError，
公开与冻结公开均未通过。不能把前面断言通过宣称为 locate 全部语义正确；过滤 None 也不证明
保留了合法 None 数据。正常行为公开检查通过，但独立验收不接受整项补丁，最终回滚。

**信息缺口：**公开 Reproduce 在一个测试方法中串联 locate 与 replace 场景。初始候选在
locate 抛异常后，后面的 replace 缺陷场景没有执行。运行证据只显示 locate 的失败路径及
Preserve 中 window_size=1 的正常 replace 调用，未展示 replace 的异常窗口。
这解释了本轮证据覆盖的边界；不能断言它是模型漏修 replace 的唯一原因，因为测试代码本身
已经给出后续场景。

**决定：原型保留，不接入默认、不扩大任务集。**实际结果为 0/1 → 0/1，只有局部断言与
补丁可执行性进展，没有整项修复成功率提升。后续若继续，应先让独立公开复现场景都能执行，
避免一个异常遮挡其他待修复路径；独立评分与认证检查不放宽。完整五十项成绩仍为 32/50。

[紧凑逐项结果](predicate-runtime-v1.json)保留运行事实、正式配对、首轮一致性、全部预算和
前期消耗。两轮合计新增推理 19617 Token；该数字不含再次计入任务预算的历史首轮用量。
