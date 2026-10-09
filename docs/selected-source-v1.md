# 模型选择源码：检索与修复分开

目标仍是固定 50 项至少通过 38 项；当前完整结果最高 33/50。连续重试的开发集对照为 21/30 → 20/30，额外 Token 增加 64.7%，不采用。

本轮检验：固定检索片段可能遗漏真正需要修改的调用者或初始化函数。先将允许编辑的原始源码解析为函数/方法签名与文档摘要，再让模型选取最多五个符号，读取其源码并生成补丁。模型可选列表按已有种子及描述词汇排序，最多 7,000 字符；并非保证整个仓库都出现在概览中。未引入参考答案、私有评分或按任务编写的提示。

## 流程和对照

1. fixed-seeds：已有固定片段，最多两次补丁调用。
2. model-selected：额外一次 JSON 符号选择调用，然后最多两次补丁调用。
3. 两组均为 DeepSeek Flash 无思考、15,000 总 Token、单次输出最多 4,096、16,000 上下文预算、600 秒超时；源码最多五段/6,000 字符。
4. 选取调用也消耗共享预算。选择无效直接失败，不免费重试；大函数按完整行截断并标记不完整。
5. 编辑和测试失败反馈、独立评分、冻结检查及失败回滚保留；修正前重新读取选中符号的当前源码并更新哈希。

30 项开发集两组独立新跑并交替顺序，包含原先成功任务以识别退步。首轮回答不复用，存在云模型生成波动；结果不能单凭差异证明机制的因果收益。开发集出现净收益后才新跑完整 50 项，不能拼接历史成功。

## 实现和运行

- [AST 概览与选取](experiments/model_source_selection_v1.py)
- [修复与反馈](experiments/selected_source_repair_v1.py)
- [配对执行器](experiments/selected_source_compare_v1.py)
- [源码选取测试](../tests/test_model_source_selection.py)

实验为可选脚本，未修改默认 Agent 或冻结旧实验代码。全部临时文件保存在 D 盘。

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp'
$env:TMP = $env:TEMP
python -B -m docs.experiments.selected_source_compare_v1 --scope development --output .tmp/real-defects/selected-source-v1-development-new
```

## 完整开发集结果（2026-10-09）

`.tmp/real-defects/selected-source-v1-development/experiment.json`：complete=true，60/60，协议输入哈希核对通过，无缺失使用量。两组均为30项。

| 指标 | fixed-seeds | model-selected |
| --- | ---: | ---: |
| 独立验收通过 | 20/30 | 19/30 |
| 最终 Controls 通过（含失败回滚） | 30/30 | 30/30 |
| 模型调用 | 47 | 76 |
| Token | 130,684 | 186,706 |
| Worker 累计秒数 | 151.60 | 176.28 |

同轮新增成功：more-bucket-missing-key；成功丢失：click-echo-empty-bytes、toolz-join-unmatched。Token 增加42.9%，通过数少1项。不推广，不继续运行此策略的完整50项，不修改默认流程。

核对报告：[固定片段](selected-source-v1-development-fixed.json)、[模型选取](selected-source-v1-development-selected.json)。报告中的gain/lost是相对历史20/30；上表后的名单则是本轮两组直接对照，不能混用。

失败证据：join已读取完整目标函数（首轮3,857字符），echo已读取echo和两个相关函数，仍两轮公开验证失败；flag-default-map读取get_default、lookup_default和构造函数后仍失败。这些案例不支持把失败统一归因为缺少源码。predicate-sentinel第二轮尝试编辑未提供的代码片段，被校验拒绝并回滚，说明固定读取后的修正仍有上下文边界。

本轮没有出现Token预算停止。结果是语义修复失败与个别编辑越界，继续增大选取概览或重试次数缺少收益依据。下一项值得检验的是在足够输出与总预算下使用更强推理，再用同批开发任务检测是否有净收益；此前低思考/小输出的两项试跑不足以判断完整任务池。仍须新跑50项至少38项通过才能宣称达到目标。

验证：源码选取与既有修正测试16 passed；新选取修复流程测试2 passed（覆盖选择失败回滚、当前符号刷新）。完整回归1454 passed、4 skipped，完成后新增的两项测试另行通过；Ruff与git diff --check通过。

