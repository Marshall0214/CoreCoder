# 均衡区间装填：跨文件迁移验收 v1

## 本轮完成的闭环

将已冻结的 `public-balanced-v1` 应用于已登记跨文件开发任务 `click-flag-envvar`，完成离线选择检查、协议冻结、两组真实补丁调用、父进程独立验收与成本分析。算法、12 行窗口和公开标识符前后 4 行参数均未修改。

本轮不是新增检索或定义工具的试验：复用历史共享定位 checkpoint，比较相同候选池的两种装填，只有 fragments 改变。两组同一源码、描述、模型和 6,000 字符证据预算；补丁额度 15,000、保留额度 3,000，各一次调用，未重跑定位。不存在根据 Target 失败反馈追加修复的调用。

公开描述包含 `flag_value`，没有精确 API 名字；本轮 `bare_names=[]`，没有指定类型转换方法或修复行号。策略按此前已实现的候选窗口回退规则运行。新入口 `balanced_crossfile_live_v1.py` 复用旧补丁函数，要求两个分支 checkpoint 哈希完全相同，冻结策略/适配器及 admission 输入；Worker 仅得到公开 Controls，Target 留在父进程评分。

## 离线选择结果

| 指标 | 原 read-first | public-balanced-v1 |
| --- | --- | --- |
| 证据内容字符 | 5,944 | 5,917 |
| 可见源码文件 | core.py、types.py | core.py、types.py |
| 原文片段数 | 8 | 11 |
| 可见 flag_value 字面锚点 | 9 / 14 | 7 / 14 |
| 显式 API 定义锚点 | 无 | 无 |

没有超预算或引入候选池以外的源码。新策略改变了两文件间区间分配，增加了部分 types.py 区间，但丢掉了另一些 core.py 区间。这里的字面锚点数量不代表需求覆盖率，也不能确定所缺行就是修复位置。没有显式 API 锚点时，均衡策略依赖通用回退规则，不能保证语义相关性。

## 真实模型与独立验收

Ollama `qwen3.5:27b`，temperature=0、reasoning=none；每组一次，使用同一候选池和相同非证据提示。

| 指标 | 原 read-first | public-balanced-v1 |
| --- | --- | --- |
| 模型调用 | 1 | 1 |
| 新补丁 Token | 3,533 | 4,117 |
| 补丁应用 | 成功 | 成功 |
| 修改文件 | core.py | core.py、types.py |
| Target（3 个测试方法） | **失败** | **失败** |
| 公开 Controls（3 个测试方法） | 通过 | 通过 |
| 源码范围违规 | 无 | 无 |
| 最终状态 | failed_verification | failed_verification |

两组没有预算拦截、无超时和验证执行错误。原 read-first 修改环境变量解析，尝试过滤 false-like 字符串；新策略修改上游空值读取条件，并为布尔类型转换增加空白字符串处理。独立验收仍发现环境变量激活/停用行为不满足要求；新策略的布尔空白验证也失败。

这些观察来自两组补丁与父进程最终日志，不向本轮模型反馈 Target 内容。新策略触发跨文件修改，不等于它正确处理了跨文件行为：类型转换处的局部修改也可能受上游处理影响。现有试验没有隔离覆盖、顺序、片段边界和模型推理各自的因果贡献。

## 成本与结论

本轮新消耗 **7,650 Token、2 次模型调用**。历史共享定位 **8,085 Token** 只计一次；历史定位与本轮对照合计 **15,735 Token**。两个单独分支的等价流水线成本分别为 **11,618 / 12,202 Token**，它们相加会重复包含共享定位，不是本轮实际消耗。

新入口原报告已明确区分 `actual_new_patch_tokens`、`shared_actual_localization_tokens`、`historical_plus_new_actual_tokens` 与两个分支的 `pipeline_tokens` 之和，避免上一轮汇总字段的歧义。通用分析器再次核对共享 checkpoint 与候选池，独立计算去重口径。

**上轮 prompt-suffix 的成功未在这个跨文件任务上复现。** 本例新策略消耗更多 Token、修改了两个文件，但未改善任务验收；不能将其设为默认策略，不能宣称整体成功率提升。两轮均为开发任务、各组一次，不能视作留出集结果或统计性证据。

## 下一步

保持算法和参数不变，在剩余已登记开发任务进行同池装填对照，形成适用范围与负面结果矩阵，再决定是否保留该策略作为可选能力。对缺少精确 API 名字的任务，后续若研究结构依赖检索或执行反馈，单独冻结工作流协议，不将本次 Target 日志变成任务专属提示或特判。泛化结论仍需其他仓库及留出任务验证。

## 测试与复现

新增两项同池约束测试及相关策略、输入校验、独立评分和阶段回归共 **31 passed**，Ruff 通过。运行结束后再次验证冻结代码和输入；未跑全量测试，未执行 Git commit。

产物 `.tmp/real-defects/balanced-crossfile-live-v1/`：experiment.json、analysis.json、selection-audit.json、两组模型输入/响应、Worker 结果、Trace、patch.diff 及独立 grading 日志。运行产物被 Git 忽略，需单独保留历史 admission 和定位 checkpoint。

```powershell
python docs/experiments/balanced_crossfile_live_v1.py --output .tmp/real-defects/balanced-crossfile-live-v1-rerun --validate-only
python docs/experiments/balanced_crossfile_live_v1.py --output .tmp/real-defects/balanced-crossfile-live-v1-rerun
python -m docs.experiments.balanced_interval_analysis_v1 --run .tmp/real-defects/balanced-crossfile-live-v1-rerun
python -m pytest tests/test_balanced_crossfile.py tests/test_balanced_intervals.py tests/test_definition_patch.py tests/test_real_tasks.py tests/test_staged_replay.py -q
```

输出须为新目录。selection-audit.json 是对实际请求的附加离线检查；核心结果、成本与片段范围可通过上述运行及分析入口复现。
