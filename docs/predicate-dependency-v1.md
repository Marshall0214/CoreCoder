# predicate 缺陷：源码依赖覆盖诊断

## 结论

同一个 `more-predicate-sentinel` 开发任务，原检索与补齐依赖各重新运行三次：
**两组都 0 次通过 / 3 次重复**。这是一个任务的确定性重复，不是三个不同任务。
缺失源码依赖是真实问题，但补齐本轮三项依赖没有改善修复；不采用、不扩大任务集，完整 32/50 未变。

可以确认两类失败：首轮补丁没有修正 predicate 参数处理，第二轮输出完整函数及文档而截断。
不能据此认定模型能力是唯一原因，也不能排除其他检索/上下文问题；本轮未得到可执行的完整第二轮补丁。

## 模型究竟看到了什么

现有输入包含完整 `replace`、`locate`，而直接依赖 `windowed`、`consume` 和 `_marker` 定义未出现。
另外三个片段是 `rlocate`、`tail`、`callback_iter._reader.callback`；其中 `rlocate` 与功能相关，
但它们都不能替代上述实际调用依赖。

| 输入 | 原检索 | 补齐依赖 |
| --- | --- | --- |
| 缺陷描述 | 相同 | 相同 |
| 完整目标函数 | replace、locate | replace、locate |
| 其他源码 | rlocate、tail、callback | 完整 windowed、consume 实现体、_marker 定义 |
| 源码片段数 | 5 | 5 |
| 源码字符数 | 5930 | 5948 |

新增 [依赖诊断流程](experiments/predicate_dependency_context_v1.py) 和
[重复对照入口](experiments/predicate_dependency_compare_v1.py)。依赖片段由缺陷版本 AST 定位，
保存真实文件哈希、起止行及原文；`consume` 仅引用实现体，明确标记为非完整函数，未伪造拼接代码。
第二轮重新从当前候选提取相同依赖；源码增长时可缩短 windowed 文档展示，仍保留可执行体，
若仍超出 6000 字符则拒绝，不扩大预算。首轮实际使用完整 windowed。

人工选择依据为描述中两个函数及其原始调用关系，没有读取参考补丁或独立评分测试来构造提示。
这是已知失败任务的人工覆盖上限诊断，未实现自动依赖检索，也不是盲测。
覆盖范围只限上述直接依赖，并未提供完整模块、所有标准库实现或全部相关上下文。

## 实验条件与观测

固定 Qwen `qwen3.5:27b`、Ollama 模型身份、temperature=0、top_p=1、非思考；
每任务最多两次请求、总 15,000 Token、单次输出 2048、估算上下文 16,000、源码五段/6000 字符。
任务超时 600 秒、请求超时 60 秒、SDK 重试为零，交替执行组顺序。
两组都使用认证公开检查、冻结公开检查和相同反馈格式，不使用最近的采样或运行轨迹策略。
公开验证决定保留与回滚，最终独立 Target/Controls 在 worker 完成后才执行。

| 指标 | 原检索 | 补齐依赖 |
| --- | --- | --- |
| 同一任务三次验收 | 0/3 | 0/3 |
| 模型调用 | 6 | 6 |
| 总 Token | 25,752 | 26,064 |
| 第二轮输出截断 | 3/3 | 3/3 |
| 回滚后 Controls | 3/3 | 3/3 |
| Worker 累计耗时 | 158.82 秒 | 153.04 秒 |

12 次新调用、51,816 Token。每组重复的首轮请求和回答分别完全相同；
两组的输入不同，不能声称组间首轮相同或复用首轮回答。
没有预算预检查停止、网络错误、超时或缺失 worker 结果。

补齐组首轮回答只有 135 个 Completion Token，却删掉了 replace 尾部输出时的 `_marker` 保护条件，
没有修正前面的 `pred(*w)`；实际填充对象仍进入用户 predicate。
原组首轮为 137 Token，同样未解决缺陷。
第二轮两组每次都输出 2048 Token、finish_reason=length，完整 old/new 函数与文档的重复占用输出空间，
回答未写完、不可应用；因此不能根据截断文本判定第二轮最终语义会不会正确。
拒绝截断输出并回滚是验证流程的正常行为，最终 Controls 通过不代表首轮候选正确。

输入组成、引用元数据及可供编辑的锚点范围随策略同时变化，不能把结果单独归因于某个依赖。
确定性重复只是检查结果是否复现，不能增加任务样本量或支撑泛化结论。

## 验收与后续边界

新增七项源码引用、预算、歧义拒绝和反馈刷新测试，连同冻结反馈测试 **22 passed**。
Windows 全量 **1359 passed、4 skipped（164.15 秒）**，新增文件 Ruff 和 Git diff 格式检查通过。
运行前后原基线源码/测试及新实验源文件哈希通过复核；未使用 DeepSeek，未重跑 Docker/HTTP。
源码、记录和测试临时目录全部在 D 盘。

机器摘要：[predicate-dependency-v1.json](predicate-dependency-v1.json)。原始记录位于
`.tmp/real-defects/predicate-dependency-v1-pilot`。复跑依赖已有真实仓库准入/认证快照、独立评分环境
和冻结模型，必须指定新的输出目录。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
python -B -m docs.experiments.predicate_dependency_compare_v1 --output .tmp/real-defects/predicate-dependency-v1-rerun
```

本轮停止继续补上下文。后续可单独验证可执行代码块编辑：编辑器保留原文与文档，
模型用块标识提交替换代码，减少重复 old/docstring，仍检查唯一锚点、版本、结构和行为。
这首先解决输出可落地性；是否改善修复语义仍须独立对照，不能预先写成收益。
