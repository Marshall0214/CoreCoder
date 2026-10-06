# 定义边界读取：独立定位 pilot v1

## 本轮问题与实现

问题：在原有定位预算内，新增按符号读取完整定义的工具，能否补足缺失源码？

独立适配器 `docs/experiments/definition_localization_v1.py` 为定位阶段增加可选 `read_definition` 和通用使用提示。默认 CoreCoder、evals 引擎和旧冻结协议不修改。baseline 分支直接调用原 `localize_staged`；definition 分支保留原阶段控制、种子生成和 receipt 校验。所有定位都从新的预算计数器开始，旧 checkpoint 仅验证输入，不复用历史定位结果或费用。

运行前冻结 `docs/experiments/definition_localization_v1.json`：固定 engine 与两个适配器 SHA、模型 digest、历史 checkpoint 原始 SHA、任务来源、两组顺序、开发集属性。运行校验输入配置、源码版本、四轮上限及 12,000 Token 探索额度。每组在独立源码副本中执行，只开放阅读与搜索；新工具只从允许列表返回源码。

**这不是纯上下文装填对照。** definition 同时增加 schema 和通用提示，比较的是工具工作流整体，不单独归因给 AST。两个工具都最多 120 行；definition 的 6,000 字符限制覆盖完整 JSON，原 read_file 输出仍按原逻辑裁剪。跨工具 receipt 沿用原分组顺序，尚未改变为全局时间排序。

## 真实模型结果

任务：`click-prompt-suffix`，已观察过失败的开发任务，非留出集。Ollama `qwen3.5:27b`，temperature=0，reasoning=none；每组一次。未将研究时观察到的符号或行号放入通用系统提示。

| 指标 | 新跑 baseline | 新跑 definition |
| --- | --- | --- |
| 定位模型调用 | 3 | 2 |
| 实际返回用量 Token | 11,654 | 7,537 |
| 源码阅读调用 | 两次 read_file | 一次 read_definition |
| 阅读范围 | 83–182、60–79 | 83–191 |
| 阅读行数 / 唯一行数 | 120 / 120 | 109 / 109 |
| 读取结果间重复行 | 0 | 0 |
| 目标 prompt 定义是否完整 | 缺 183–191 | 完整 109 行 |
| read-first 装填后是否保留目标定义 | 保留不完整片段 | 保留完整片段 |
| 下一轮停止 | minimum_output_preflight | minimum_output_preflight |
| 停止时剩余预算 / 请求估算 | 346 / 4,936 | 4,463 / 5,508 |
| 源码未改动 | 是 | 是 |

总计 **19,191 Token、5 次模型调用**，无新修复调用。模型先自行定位，再主动选择 `read_definition(..., symbol="prompt")`，响应为 `complete_symbol=true`，无缺失范围；该片段进入新候选池并能通过原 read-first 的 6,000 字符装填。

重复行只统计实际阅读 receipts 之间，未包含初始 seeds 与阅读的交叠，不能据此宣称整个上下文无重复。definition 已获取完整源码，但模型没有在下一轮看到工具响应：将完整 JSON 放入历史后，下一请求估算 5,508 Token，超过剩余 4,463 加最小输出所需预算。因此本次较少用量既受工具行为影响，也受预算提前停止影响，不能简单说效率提高了 35%。

## 可以得出的结论

可选工具在真实模型调用中被使用，并补足此前缺失的函数末尾；receipt 与候选装填链路能保留完整定义。**尚未执行补丁和独立评分，不能宣称修复成功率提升。** 两组都由预检查停止，而非模型主动判断定位完成；记录为 localized 表示取得检查点，不表示定位质量合格。

产物 `.tmp/real-defects/definition-localization-v1/` 包含 protocol 副本信息、experiment.json、analysis.json、两组 Trace、源码副本、候选池和新 checkpoint。目录被忽略，重现历史输入需另外保留 admission 与旧 checkpoint；仓库代码本身不包含这些运行产物。

## 验证与下一步

新增适配器三项测试验证 baseline 请求与原入口一致、可选 schema/完整 receipt 入池、禁止编辑及预算耗尽恢复；与读取原型、阶段回归共 **27 passed**，Ruff 通过。未执行全量测试。源码读取后哈希与冻结版本一致。

下一步：用两组新检查点分别执行相同 read-first 补丁阶段，保持总预算、补丁额度和独立 Target/Controls 验证；历史定位费用作为各分支实际已发生成本记录，不再重复调用定位。若缺陷仍未修复，记录证据完整与修复能力的区别，不继续按单例补提示。扩展跨文件任务和留出集之前，先查阅 [相关开源工作](related-open-source.md)，借鉴成熟结构定位方法。

```powershell
python docs/experiments/definition_localization_v1.py --workspace .tmp/real-defects/expansion-admission-v1/click-prompt-suffix/before --output .tmp/real-defects/definition-localization-v1-rerun --validate-only
python docs/experiments/definition_localization_v1.py --workspace .tmp/real-defects/expansion-admission-v1/click-prompt-suffix/before --output .tmp/real-defects/definition-localization-v1-rerun
python -m docs.experiments.definition_localization_analysis_v1 --run .tmp/real-defects/definition-localization-v1-rerun
python -m pytest tests/test_definition_localization.py tests/test_definition_read.py tests/test_staged_repair.py -q
```
