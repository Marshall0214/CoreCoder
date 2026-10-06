# 保留连续片段的覆盖去重 v1

## 实现与规则

独立实验模块 `docs/experiments/staged_containment_packing_v1.py` 复用七份冻结候选池，保持 read-first 顺序、6,000 字符上限和完整片段。只跳过原策略的精确重复，或被**某一个已选片段**完整包含的候选；后者同时要求文件版本相同、行范围包含且完整原文为子串。

不根据多个片段的行并集去重，不删除文档，不截断部分重叠候选，不合并或补齐源码。跳过的候选不会改变已选片段内容。诊断元数据单独记录，不添加到模型证据，避免制造新的请求开销。

只有实际装入的片段才能覆盖后续候选；因预算拒绝的片段不能成为容器。含末尾空源码行的标准化 read 内容也被接受，正式入口仍通过原检查点校验器核对真实源码范围、文本和版本。

## 冻结候选池结果

| 任务 | 两组完整消息 JSON 字符 | 新策略请求是否变化 |
| --- | ---: | --- |
| help-eagerness | 8,970 | 否 |
| flag-default-map | 8,928 | 否 |
| resource-exception | 9,291 | 否 |
| flag-envvar | 11,106 | 否 |
| prompt-suffix | 10,088 | 否 |
| invoke-missing | 7,072 | 否 |
| shared-default | 8,748 | 否 |

七个 baseline 提示哈希与上一轮真实请求匹配，七个新策略完整请求也与 baseline 完全相同。全部原片段的连续编辑锚点保留，丢失行数和新增行数均为 0。

本批候选没有触发额外的单片段包含去重；最终片段和预算跳过情况与原策略相同。新算法在人工小样例中能跳过被包含的片段并为后续候选腾出空间，但**这不是实际七任务中的收益**。

因此本轮没有执行真实模型重复运行，模型调用和新增定位调用均为 **0**。不能将相同请求的历史通过率当成新策略的独立实测分数，也不宣称实际 Token 下降。完整消息 JSON 和预检查估算只用于离线对比。

## 决策与下一步

保留 read-first 默认，停止对这批相同候选继续尝试去重变体。当前去重没有改变输入，无法解决已发现的候选缺失或行为理解错误；此前删文档的 compact 又造成退化，不能用它替代这一结果。

后续 [定位获取审计](staged-acquisition-audit-v1.md) 已确认：prompt 种子被预算排除，模型请求 100 行后又重复读取 20 行，阶段预算耗尽，尾部 9 行未获取；原工具可在现有上限内一次读完 109 行定义。下一步实现可选定义边界读取原型，再冻结新定位协议；公开行为契约错误仍单独记录，补齐代码不等于已经修复。

## 复现与验证

```powershell
python docs/experiments/staged_containment_packing_v1.py --experiment .tmp/real-defects/staged-compact-live-v1-r2/experiment.json --source original=.tmp/real-defects/mixed-original-admission-v1 --source crossfile=.tmp/real-defects/crossfile-admission-v2 --source expansion=.tmp/real-defects/expansion-admission-v1 --output .tmp/real-defects/staged-containment-packing-v1-rerun
python -m pytest tests/test_staged_containment_packing.py tests/test_staged_failure_audit.py tests/test_staged_compact_live.py tests/test_staged_compact_packing.py tests/test_staged_evidence_coverage.py tests/test_staged_replay.py tests/test_staged_repair.py -q
```

输出须为新目录；需保留上一轮实验及分析、检查点和 before 源码。产物 `.tmp/real-defects/staged-containment-packing-v1/packing.json` 记录算法 SHA、输入实验 SHA、请求哈希、正文/完整请求大小、预检估算、锚点保留和逐候选原因；被 Git 忽略。

8 项新增测试及相关回归共 **48 passed**，Ruff 通过。测试覆盖单片段包含腾出容量、联合覆盖不替代连续锚点、部分重叠原文、预算拒绝候选、末尾空行、CRLF 文档编辑、原文编码差异及版本冲突。未改动原修复实现或旧协议，未重跑全量测试。
