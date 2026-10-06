# 冻结证据覆盖诊断 v1

## 目的与边界

三轮补丁重放的相同输入得到相同输出，继续重复没有新增信息。本轮离线检查七份原检查点，区分公开名称相关代码未进入候选池、只进入部分片段，以及装填时被舍弃。修复实现和默认策略不变，模型调用及新增定位调用均为 **0**。

入口：`docs/experiments/staged_evidence_coverage_v1.py`。只读取冻结协议、公开描述、检查点和各任务 `before` 的允许源码；不读取隐藏测试、评分反馈、`after` 源码或参考补丁。检查点原始 SHA、校验和、源码版本、描述、配置和修复实现均通过现有校验器核对。

## 怎么判读

- **锚点**：公开描述中的下划线标识符、点号限定名称；另将描述中明确出现的 `prompt`、`confirm` 作为人工确认的函数名记录。不把普通叙述中的 name、option、callback 等单词自动视为代码名称。
- **候选池缺失**：锚点所在行或定义范围与候选片段没有交集。
- **候选池部分覆盖**：定义范围只有部分行进入候选池；不能仅据此断定是读取上限导致的截断。
- **装填丢失**：候选池已有的锚点行未进入最终上下文。诊断重用实际 `select_evidence`，另记录每个片段因重复、超过总上限或剩余容量不足而被跳过的原因。

按源码行的并集计算，重叠片段不重复计数。函数的范围含文档字符串；完整行覆盖不等于完整语义证据，缺少某个同名引用也不等于缺少必要修复位置。声明、重载和变量引用可能是多个锚点，不能当作独立需求或成功率分母。

## 结果

| 任务 | 锚点数 | 候选池缺失 | 候选池部分覆盖 | 装填丢失锚点：read / seed |
| --- | ---: | ---: | ---: | ---: |
| help-eagerness | 0 | — | — | — |
| flag-default-map | 7 | 5 | 0 | 0 / 0 |
| resource-exception | 1 | 0 | 0 | 0 / 0 |
| flag-envvar | 14 | 5 | 0 | 0 / 6 |
| prompt-suffix | 7 | 0 | 1 | 3 / 4 |
| invoke-missing | 3 | 2 | 0 | 0 / 0 |
| shared-default | 0 | — | — | — |

缺少明确名称的两个任务无法通过本轮规则判断需求覆盖，不能解释为证据完整。其余任务的统计也只是排查线索。

最明确的案例是 **prompt-suffix**，公开描述同时要求 `prompt` 和 `confirm`：

- 原源码 `termui.py` 中 `prompt` 为 83–191 行，候选池只覆盖 83–182 行，尾部 9 行缺失。
- `confirm` 为 194–252 行，59 行完整进入候选池。
- read-first 装填 5,735 字符，保留 `prompt` 的 100 行，却因剩余容量不足丢弃完整 `confirm` 片段。
- seed-first 装填 5,773 字符，保留完整 `confirm`，却丢弃 `prompt` 的片段。

这证实当前装填策略存在互相挤出的情况，并且候选池本身也有不完整片段。它没有证明这些缺口是验收失败的全部原因。

其他观察：flag-envvar 在 seed-first 下额外丢失 6 处 `flag_value` 引用；resource-exception 的 `with_resource` 完整可见但仍失败，说明名称覆盖不能替代调用链分析或修复能力。invoke-missing 的运行时实现完整可见，而两个重载声明未进入候选池；read-first 实际通过，说明“所有声明都覆盖”不是必要验收条件。

## 决策

后续已实现 [紧凑装填离线原型](staged-compact-packing-v1.md)：在同一候选池、6,000 字符上限下去重并移除完整文档字符串，prompt-suffix 同时保留了 prompt 已有代码和 confirm 完整非文档范围。分段元数据使部分任务 JSON 变长，尚未获得真实修复或 Token 收益结论。下一步冻结协议并接入显式补丁实验；不要按隐藏测试挑片段，也不要将缺失的源码伪装成已检索证据。

紧凑装填只解决装填阶段，不能恢复 `prompt` 缺失的 9 行。若随后改变读取或补全定义边界，需要单独版本化定位协议和检查点，分别评价两项改动。保留 read-first 默认，未获得独立验收收益前不推广新策略。

## 复跑与验证

```powershell
python docs/experiments/staged_evidence_coverage_v1.py --source original=.tmp/real-defects/mixed-original-admission-v1 --source crossfile=.tmp/real-defects/crossfile-admission-v2 --source expansion=.tmp/real-defects/expansion-admission-v1 --output .tmp/real-defects/staged-evidence-coverage-v1-rerun
```

输出必须是不存在的新目录。需要保留原七份检查点及 `before` 源码；原始产物被 Git 忽略，克隆仓库不包含它们。

最终产物：`.tmp/real-defects/staged-evidence-coverage-v1-final-v2/coverage.json`，记录诊断脚本 SHA、协议 SHA、检查点 SHA、源码版本、逐锚点行数及装填原因。早期诊断产物保留用于审计，不用于本文结果。

本轮相关测试 19 passed，含 5 项新诊断测试；Ruff 通过。覆盖限定名称匹配、普通叙述排除、候选池缺失与部分覆盖、装填丢失、重叠去重、超长片段及注释/字符串排除。修复实现未修改，未重跑全量测试。
