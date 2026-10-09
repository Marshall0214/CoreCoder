# 有界连续修正：两次与四次调用对照

更新：2026-10-09。目标仍为固定 50 项至少通过 38 项；当前完整 DeepSeek 配置已验收 33/50，目标尚未达到。

## 依据和实现

Aider 将编辑格式错误及测试失败送回修正循环，见 [源码](https://github.com/Aider-AI/aider/blob/main/aider/coders/base_coder.py)、[测试机制](https://aider.chat/docs/usage/lint-test.html)。本轮借鉴失败恢复与有界循环，不直接移植其编辑器，也不宣称拥有 Aider 基准上的效果。

旧流程第一轮编辑无效/截断通常直接结束，应用成功后最多一次测试反馈。新增独立实验工作流：

1. 校验任务源码、证据及公开检查哈希，保存原始副本。
2. 请求候选补丁，原子应用并检查语法。
3. 编辑失败恢复本轮修改前状态，将实际错误及当前证据交回模型。
4. 编辑成功执行当前轮公开与冻结保持检查；未通过则针对当前候选继续修正，不反复使用首轮日志。
5. 通过立即停止；调用上限、预算停止、测试执行故障或异常使任务结束。最终未通过恢复原始源码。
6. Worker 外使用未传给模型的独立评分检查验收。公开通过仍不能代替最终验收。

代码：[连续修正](experiments/bounded_repair_loop_v1.py)、[配对执行器](experiments/bounded_repair_compare_v1.py)、[回归测试](../tests/test_bounded_repair_loop.py)。不修改既有冻结流程或默认 Agent/API。

本轮暂不加入按需补读、仓库地图或 Architect/Editor，避免与调用次数干预混合；源码证据仍按已有种子刷新，最多五段/6,000 字符。

## 固定协议

| 项目 | 两次组 | 四次组 |
| --- | --- | --- |
| 最大模型调用 | 2 | 4 |
| 模型与开关 | DeepSeek Flash、无思考、JSON 输出 | 相同 |
| 总 Token 预算 | 15,000 | 15,000 |
| 单次输出上限 | 4,096，按剩余预算降低 | 相同 |
| 上下文预算 / 超时 | 16,000 / 600 秒 | 相同 |
| 检索、错误反馈、评分、回滚 | 相同 | 相同 |

每项两组从独立原始副本新跑，交替顺序；全部 30 项开发任务都参与，保留失败与原有成功的退步。预算包含重复输入；四次上限不保证实际能调用四次。历史 DeepSeek 的 8,192 输出上限与本轮不同，不能直接把所有变化归因于增加轮次。

## 当前状态

- 历史全量核对已完成：[DeepSeek 完整结果](deepseek-direct-v1-full.json)，32/50 → 33/50，新增 6、丢失 5；70 调用、195,101 Token，未达到 75%。
- 本轮聚焦测试 **24 passed**，覆盖编辑失败恢复、第三次成功、上限、预算停止、提前成功、检查防篡改及当前轮日志。
- 本轮 30 项配对已完成（60/60）：两次组 21/30、四次组 20/30；Token 116,154 → 191,266（+64.7%）。没有净收益，不推广四次重试。核对报告见 [两次组](bounded-repair-v1-development-loop2.json)、[四次组](bounded-repair-v1-development-loop4.json)。
- 完整回归 **1445 passed、4 skipped（170.91 秒）**，Ruff 通过。

所有输出和临时目录均在 D 盘。未发布、未提交 Git，不把人工补丁或参考答案交给模型。

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp'
$env:TMP = $env:TEMP
python -B -m docs.experiments.bounded_repair_compare_v1 --scope development --output .tmp/real-defects/bounded-repair-v1-development-new
```

每次复现使用新目录。开发集若有净提升，再固定该配置新跑完整 50 项，不拼接历史或其他策略的成功补丁。

首批真实任务：四次组的 none-salt 在第三次调用后独立验收通过，两次组未通过；resource 任务出现相反结果，两次组通过、四次组失败。因此不能用单例宣称整体提升。两组首轮输入相同但回答不复用，云模型生成差异可能影响净结果；完整开发集作为探索性对照，若推广仍需新跑完整任务池。
