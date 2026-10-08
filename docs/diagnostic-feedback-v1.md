# 第二轮修正：均衡失败诊断与最小补丁

## 要修正的问题

前一轮 `failure-context-v1` 两组均为 2/8。新增执行邻域函数没有带来新增成功。
逐项检查表明：Usage 修改了错误分支；Join 消除了 NameError，却仍重复输出；资源异常
复现通过，却因提前返回跳过上下文清理；predicate 的第二轮完整函数替换被 2048 Token
输出上限截断。它们分别涉及诊断、回归和补丁表达，不能全部归因于检索不足。

旧反馈先拼接公开与冻结公开日志，再整体截断。多组长日志可能让后面的正常行为失败
不完整。模型虽已有测试代码，但没有明确的分组结果和首轮修改摘要。

## 本次改动

- 保留原来的源码种子刷新，不采用无增益的执行邻域重排。
- 单独列出 public/frozen 的 Reproduce/Preserve 成败及运行数量，保留通过的约束。
- 每个失败组最多展示四条失败的测试名与断言尾部；相同内容去重，避免整体日志先到先得。
- 附上首轮候选的局部 diff，总计最多 1600 字符；只读模型刚生成的补丁。
- 明确要求局部、唯一匹配的 old/new，避免复制未改动的完整函数与文档字符串。
- 要求检查受影响的分支、排序、清理和重复输出；这些是通用审查问题，不是已经确认的根因。

这是提示与证据组织改进，不保证模型一定输出小补丁，也不提高输出上限。失败细节与 diff
仍可能截断；元数据注明了限制。暂不增加局部变量探测、额外诊断调用或第三次修复。

## 实验协议

沿用前一轮八个开发任务：六个已知失败、两个成功回归检查。不是盲测，也不是完整五十项。
`unchanged-feedback` 对比 `diagnostic-feedback`，每项各一次，交替顺序；都重新请求首轮。

固定 qwen3.5:27b、非思考、temperature=0、top_p=1，最多两次调用、累计 15000 Token、
单次输出 2048 Token、上下文 16000、单项 600 秒。首轮输入、源码上下文、检查、独立评分
和失败回滚不变。只读取认证公开测试、公开检查结果和首轮补丁，不向模型提供 Target/Controls
或参考修复。改动基于已知开发失败设计，不能宣称独立泛化提升。

代码：[反馈策略](experiments/diagnostic_feedback_v1.py)、
[配对执行](experiments/diagnostic_feedback_compare_v1.py)、
[测试](../tests/test_diagnostic_feedback.py)。默认 Agent/API 未变。

## 复现

激活 corecoder 后执行；输出目录必须尚不存在，所有临时输出位于 D 盘：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp'
$env:TMP = $env:TEMP
python -B -m pytest tests/test_diagnostic_feedback.py tests/test_frozen_feedback.py tests/test_failure_guided_context.py -q
python -B -m docs.experiments.diagnostic_feedback_compare_v1 --output .tmp/real-defects/diagnostic-feedback-v1-new
```

历史来源：已完成的 `system-comparison-v1-rerun`。新配对记录保存在
`.tmp/real-defects/diagnostic-feedback-v1-pilot/experiment.json`，其中 `complete=true` 才代表全部完成。
完整五十项历史成绩仍为 32/50；本实验不替换它。

## 验证与结果

相关测试 27 项通过，Ruff 通过。全量复测 **1323 passed、4 skipped**。
首次全量执行为 1321 passed、4 skipped、2 failed；两个失败均为独立验证子进程
向 `tests/.pytest_tmp` 写结果 JSON 被拒绝，断言本身已执行。单独复测在原目录仍失败；
指定新的 D 盘项目内 `--basetemp` 后相关六项及完整测试均通过，未更改验证器或评分规则。

| 方案 | 修复通过 | 最终正常行为通过 | 调用 | Token | Worker 总秒数 |
| --- | --- | --- | --- | --- | --- |
| unchanged-feedback | 2/8 | 8/8 | 15 | 48,509 | 239.6 |
| diagnostic-feedback | 1/8 | 8/8 | 15 | 49,438 | 198.4 |

首轮请求及回答均 8/8 相同。新增成功 0 项、丢失成功 1 项（none-salt）。最终正常行为通过
包含失败回滚，不能解释为候选补丁全部保持正常行为。Token 增加 929，约 1.9%；不同 worker
耗时不能据此认定稳定性能收益。

**具体变化：**predicate 第二轮由 `output_truncated`（2048 输出 Token）变为完整且可应用的
局部补丁（229 输出 Token）。正常行为通过，但目标断言仍失败：最后一次 predicate 收到
`(3, 4)`，而不是预期 `(4,)`。说明截断阻碍被消除，尾部窗口语义仍未修对。资源异常修正
因 old 文本不属于给定上下文被拒绝；none-salt 修正可应用且正常行为通过，但签名一致性
目标仍失败。检查与回滚没有为这些错误补丁放宽。

**决定：不采用、不扩大运行。**本轮修正了反馈展示的机制，并在一个样例消除了截断，
却没有提高整体修复效果。不能把提示改动或测试通过写成成功率提升。默认 Agent/API 和
原 32/50 方案保持不变；不在本轮继续叠加提示或追跑完整五十项。

[逐项结果](diagnostic-feedback-v1.json)保留两组状态、预算、首轮一致性及冻结输入哈希。
原实验目录保留完整请求、补丁和目标/正常行为验证日志。
