# 公开锚点均衡区间装填：实现与完整验收

## 做了什么

新增独立策略 `docs/experiments/balanced_intervals_v1.py`，在冻结候选池与固定 6,000 字符预算内，以真实源码区间分配证据。公开 API 的名字沿用上一轮公开锚点声明，不使用隐藏测试或参考补丁。对每个 API 轮流尝试：声明前 12 行、公开标识符附近各 4 行、其余 12 行窗口；候选依赖作为回退组参与。选择顺序和窗口常量在真实调用前固定。

算法不删除 docstring、不执行源码。它可以因预算略去某些原文区间，但会报告完整性和缺失范围。选中行必须已经存在于 reads/seeds 的并集，校验源码字节 SHA 与每条候选原文；连续的已选行合并为原文片段，存在缺口时保留为不同片段，不构造假的连续编辑锚点。总内容字符包括合并后的换行，逐次校验预算；不截断单行。

为了保持旧实验可复跑，默认 CoreCoder/evals 和旧协议不改。`balanced_interval_live_v1.py` 是可运行实验入口：同一 definition 定位 checkpoint 分别走原 read-first 和新策略，独立 Worker 执行相同补丁机制，再由父进程进行 Target/Controls 验收。新协议固定适配器/策略 SHA、checkpoint/候选池、源码输入、模型 digest、公开描述及预算。

本轮完成了 **实现 → 测试 → 冻结 → 真实模型对照 → 独立评分 → 成本与失败分析**。

## 对照条件与结果

任务为已反复研究的开发任务 `click-prompt-suffix`，每组一次；Ollama `qwen3.5:27b`，temperature=0、reasoning=none。两组复用完全相同的 7,537 Token 定位结果，**只有发给补丁模型的 fragments 改变**：非证据提示哈希相同，候选池哈希相同，补丁额度均为 15,000，验证保留 3,000。本轮不再次执行定位。

| 指标 | 原 read-first | public-balanced-v1 |
| --- | --- | --- |
| 证据内容字符 | 5,172 | 5,991 |
| confirm 可见范围 | 无 | 194–252，完整 59 行 |
| prompt 可见范围 | 83–191，完整 109 行 | 83–178、191，共 97 行 |
| prompt 缺失范围 | 无 | 179–190 |
| 补丁模型调用 | 1 | 1 |
| 本轮 Token | 2,830 | 2,770 |
| Target | 失败 | **通过** |
| 公开 Controls | 通过 | **通过** |
| 源码范围违规 | 无 | 无 |
| 最终结果 | failed_verification | **passed** |

新策略最终选中 init.py 的一行引用，以及 termui.py 的上述三段原文；其余候选没有全部保留。它取得的是多处相关实现之间的取舍，不是把两个函数都完整装下。

原 read-first 仍只对 `_build_prompt` 生成字符串输入下行为等价的修改。新策略生成了两处真正行为变化：在 `prompt` 和 `confirm` 的交互输入流程中，区分空 `prompt_suffix`；非空后缀沿用原路径，空后缀不再向输入函数传入额外空格。两处修改均来自实际展示的片段，补丁合法应用后由父进程独立验证。

Target 和 Controls 各运行一个测试方法，均未超时；Controls 不代表完整 Click 上游回归套件。通过结果意味着修复了当前独立验证器覆盖的缺陷，不代表所有 Click 行为已验证。

## 成本口径

本轮新消耗 **5,600 Token、2 次模型调用**。一份历史共享定位为 7,537 Token；本对照去重后包含历史定位与本轮调用的成本为 **13,137 Token**。单独部署每种分支的等价流水线成本为 10,367 / 10,307 Token。

原运行器的 `pipeline_tokens=20,674` 是两个独立分支等价成本之和，重复包含共享定位；`previous_actual_localization_tokens` 同样沿用了分支相加口径。不可将这两个字段当成本次实际消耗。冻结原始报告保持原样；`balanced_interval_analysis_v1.py` 输出 `shared_actual_localization_tokens`、`historical_plus_new_actual_tokens` 和明确说明，将同一 checkpoint 按哈希去重。该成本口径有独立测试。

## 结论与限制

在**这个已研究过的开发任务**上，同一候选池和预算下，均衡原文区间装填比原 read-first 得到了更有效的补丁，完成了独立缺陷验收。这是可以复现的正面结果，可以记录为具体案例。

不能写成普遍提高成功率或优于成熟 Agent：每组一次，选择该问题受到前期失败分析影响，公开 bare API 名字由此前诊断明确声明；新的证据同时改变覆盖、顺序、片段边界、元数据和依赖取舍，不能单独归因给“展示 confirm”。词面锚点不能保证跨文件语义依赖完整，省略 prompt 尾部在其他缺陷上也可能有害。

本策略暂不成为默认 Agent 行为。下一步在已登记的跨文件开发任务上，用同样算法与固定窗口参数进行离线选择诊断，再冻结完整工作流对照；不因本次成功追加特殊规则。最后仍需要其他仓库与留出任务来验证泛化。

## 验证、产物与运行

新增八项测试及相关回归共 **28 passed**，Ruff 通过。覆盖源码/版本漂移、CRLF/Unicode、极小预算及超长行、候选缺口不能变成可编辑连续文本、小预算多 API 覆盖与确定性、补丁提示非证据不变、共享定位成本去重。未执行全量测试。

产物 `.tmp/real-defects/balanced-interval-live-v1/` 包含冻结协议信息、experiment.json、analysis.json、两组模型输入/响应、Trace、Worker 结果、patch.diff 和父进程 grading 日志，运行产物被 Git 忽略。需单独保留历史 admission 和定位 checkpoint 才能复跑。

```powershell
python docs/experiments/balanced_interval_live_v1.py --output .tmp/real-defects/balanced-interval-live-v1-rerun --validate-only
python docs/experiments/balanced_interval_live_v1.py --output .tmp/real-defects/balanced-interval-live-v1-rerun
python -m docs.experiments.balanced_interval_analysis_v1 --run .tmp/real-defects/balanced-interval-live-v1-rerun
python -m pytest tests/test_balanced_intervals.py tests/test_staged_compact_live.py tests/test_definition_patch.py tests/test_public_coverage_followup.py tests/test_staged_replay.py -q
```

输出必须是新目录。没有执行 Git commit。
