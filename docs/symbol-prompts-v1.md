# 局部补丁公开行为核对：Prompt 对照 v1

## 改动与控制条件

新增可选 `behavior-check` Prompt 策略。将公开问题描述按标点/换行拆为原文条目，每条附字符范围，可验证其确实来自公开描述；这只是句段拆分，不是完整的语义需求解析。要求模型核对描述已提及的正例、反例、边界与保留行为，并区分激活判定和参数转换。补丁继续只返回 edits，不增加工具、检查生成或反馈轮次。

默认 baseline 请求保持原有描述和局部片段结构。两组使用完全相同证据，behavior-check 多出原文条目和核对指令。核对属于 Prompt 引导，并无机器验证其完成；Trace 明确 semantic_coverage_verified false。条目提取不访问 Target、参考补丁或官方修改文件列表。

`evals.compare_symbol_prompts` 冻结实现、依赖、准入源码和验收版本，按 baseline / behavior-check、behavior-check / baseline、baseline / behavior-check 顺序运行三轮。每次独立源码副本、一次补丁请求、父进程独立评分，隐藏结果不回传模型。两组固定索引、查询、证据预算、依赖深度及模型设置；检查共同证据摘要和工具摘要、每组内 Prompt 摘要及模型 manifest 摘要。

此次仍是一个已知开发任务上的 Prompt 实验，不是检索消融、留出评测或总体成功率。Prompt 被公开需求和已知开发失败启发，不能视为盲测；原失败保留。

## 冷启动元数据问题

初次 `.tmp/real-defects/symbol-prompts-v1` 仅完成一份 baseline 后中止：请求前 `/api/ps` 中模型未载入，无法确认摘要。该记录不并入后续完整对照。

修正模型身份读取：Worker 额外采集 `/api/tags` 中对应已安装模型的 name/digest，不依赖显存驻留。对照在每次请求前后要求同一 manifest 摘要；仍记录 `/api/ps` 的载入状态。未放松缺失或变化摘要的检查。最终完整对照使用新目录 symbol-prompts-v2。

## 完整对照结果

最终 `.tmp/real-defects/symbol-prompts-v2` 完成 6/6，模型摘要固定为 `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`，实现摘要 `6aad4e79b79f3db75d60ccdb5825a718217982997745cf2c286eb25ee8aa669d`。两组正文均 5,764 字符，证据摘要一致；每组内 Prompt 摘要固定。

| 策略 | 独立验收通过 | 合法补丁 | 公开 Controls | 总 Token | 平均总耗时 |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | 0/3 | 3/3 | 3/3 组通过 | 11,001 | 12.9086 秒 |
| behavior-check | 0/3 | 3/3 | 3/3 组通过 | 12,285 | 18.0646 秒 |

两组都只修改 core.py，未修改已展示的 types.py。baseline 使用参数转换结果判定激活；behavior-check 增加显式真假值/精确匹配判断，但不匹配时返回 None，仍未满足未激活时的预期语义，布尔转换模块也没有补丁。Target 六次均失败。以上来自验收后的开发者分析，不反馈模型，不据此改写隐藏测试。

每次 baseline 为 3,667 Token，behavior-check 为 4,095 Token，总量增加约 11.7%，未带来最终成功。temperature 0 的三次输出具有重复性；同一个开发任务的重复运行不是三个独立缺陷样本，不能给出普遍提升或统计显著性。耗时包含本机运行影响，仅作记录。

结论：保持 baseline 默认。原文条目与核对指令能影响补丁，却不能替代实际行为验证。下一步应基于公开需求设计可执行的开发检查，检查未激活语义、布尔空白值及保留行为，再以单独反馈协议评估；不从隐藏验收复制用例或结果。

测试：全量 539 passed、1 skipped，相关文件 Ruff 通过；新增覆盖原文范围、证据一致、Prompt 差异、冻结顺序、证据变化中止，以及模型未载入时的身份读取。中止批次 v1 保留，成绩不合并。

## 复现步骤

```powershell
python -m pytest tests/test_symbol_patch.py tests/test_symbol_prompt_comparison.py -q
python -m evals.compare_symbol_prompts --admission .tmp/real-defects/crossfile-admission-v2/admission.json --repeat 3 --output .tmp/real-defects/symbol-prompts-reproduction
python -m pytest tests -q
```

要求对应准入报告/源码与本地 Ollama qwen3.5:27b 已存在；输出目录须是新目录。freeze.json 保存预定顺序和配置，comparison.json 增量保留各次结果；每次目录保存响应、补丁、Trace 和独立验收日志。对照 CLI 退出 0 表示所有计划运行完成且身份检查通过，不表示补丁成功。
