# 按函数替换：实现与停止结论

本轮解决的是模型复述 `old` 片段漏行导致补丁无法匹配的问题。已实现可选的“函数标识 + 文件版本 + 完整函数替换”协议，但两项行为验收未证明修复效果改善，因此不接入默认 Agent，不扩大任务集。机器摘要见 [function-replace-v1.json](function-replace-v1.json)。

## 实际改动

仅第二轮反馈请求切换协议；第一轮仍使用原有唯一片段替换。模型提交 `file`、`symbol`、文件 SHA256 `content_hash` 和完整 `new` 函数，无需复述旧代码或提供行号。程序从当前源码 AST 定位函数，确认它已完整展示给模型，自动提取旧文本，再交给已有唯一匹配和结构检查事务执行。

拒绝过期文件版本、未展示或不完整的函数、重复或重叠目标、歧义声明、越界文件、改名、同步/异步类型改变、装饰器改变和额外顶层语句。保留原缩进和换行格式。AST 行号仅用于程序内部定位。编译和导入通过并不代表业务行为正确。

实现：`docs/experiments/function_replace_v1.py` / `function_replace_v2.py`；对应 worker、配对驱动与回放驱动均版本化保存。未修改冻结引擎、历史实验或服务。离线审计用历史答案验证了四个函数的定位与转换，无新增模型调用。

## 真实配对与答案回放

固定 Qwen `qwen3.5:27b`、工具、两次调用、15,000 Token 预算、6,000 字符/最多五个函数证据和原评测协议。候选不使用上轮补丁差异历史。

| 任务 | 基线 | 函数替换 v1 | 同答案回放 v2 |
| --- | --- | --- | --- |
| Click 空参数用法输出 | 通过 | JSON 解析拒绝 | 行为验收失败 |
| itsdangerous none-salt | 行为验收失败 | JSON 解析拒绝 | 行为验收失败 |

v1 共八次本地模型调用、34,137 Token。候选两次反馈返回整个 Markdown JSON 代码块，被严格 JSON 解析拒绝；这是输出封装问题，不能当成函数定位失败。冻结 v1 后，v2 仅兼容单个完整 JSON/无标签代码块，两组均应用相同解析处理；拒绝解释文字、多代码块和其他语言标签，不放宽源码检查。

v2 复用上述八个答案，零新增推理；六个请求完全一致，两个仅归一化 unittest 耗时文本后匹配。独立执行四次任务验收。候选两项反馈事务均成功定位并提交，但目标与 Controls 均失败：Click 未正确处理空参数输出并破坏非空参数换行；none-salt 仍将 `None` 改为固定默认值且未恢复被删除的回退逻辑。最终基线 1/2、候选 0/2。

回放中的调用量和 Token 是历史用量，不能再次累计。只有两项已检查任务，不能据此推断总体修复率。实验在可丢弃工作区直接提交候选，未应用服务的最终语义发布门禁。

## 验证与后续

新增测试 25 项通过；Windows 全量 **1,169 passed、2 skipped，187.75 秒**；Ruff 通过。模型身份及冻结输入哈希校验通过。未调用 DeepSeek，未重跑 Linux、容器或 HTTP 验收；临时数据位于 D 盘。

本轮关闭编辑格式优化，保留可选原型。下一步核心问题是修改后的参数语义和行为保持：正确落到函数上之后，仍需生成满足边界输入与原行为的修复，不能将结构有效误报为缺陷已修复。

复现入口（需要已有历史任务、审计数据和本地 Qwen 环境，输出目录必须全新）：

```powershell
python -m docs.experiments.function_replace_compare_v1 --output .tmp/real-defects/function-replace-compare-v1-new
python -m docs.experiments.function_replace_replay_v2 --output .tmp/real-defects/function-replace-replay-v2-new
```

回放固定读取 `.tmp/real-defects/function-replace-compare-v1` 的历史答案，不会自动使用新运行目录。原始记录保存在该目录的 `experiment.json` 与 `.tmp/real-defects/function-replace-replay-v2/replay.json`，摘要保存来源哈希；仅拉取 Git 仓库不包含这些忽略的运行工件。
