# 紧凑证据装填 v1：离线原型

## 本轮实现

新增独立实验模块 `docs/experiments/staged_compact_packing_v1.py`，提供 `compact_evidence` 和七任务对比入口。复用原冻结候选池，保持 read-first 的候选顺序及 6,000 字符正文上限；不改变 `corecoder/`、`evals/` 修复实现或默认策略，不需要重建检查点。模型调用和新增定位调用均为 **0**。

紧凑装填执行三项操作：

1. 根据原始源码 AST 识别模块、类和函数的首个文档字符串；只在其完整范围已进入候选池、且独占源码行时移除。部分文档字符串、与代码共用一行的字符串以及运行时字符串保留。语法无法解析时保留文本。
2. 去除已装入的重叠行，按剩余连续行拆成片段；不拼接跨越缺口的伪源码。每片保留真实起止行、文件 SHA、来源候选及原范围，内容逐字对应原始源码，保留 CRLF。
3. 某个候选压缩后新增的所有片段整体能装入才接纳，不能装入则整体跳过，不为塞满预算再截断代码。

原始 `before` 源码只用于确认版本、文档字符串范围及原文，输出行必须来自候选池。没有补读或补全缺失行。校验失败时拒绝运行，原检查点和候选池不被修改。实验模块尚未接入真实修复请求；现有补丁校验器对这种分段证据的兼容性通过测试验证。

## 离线结果

| 任务 | 正文字符：原策略 → 紧凑 | 片段 JSON 字符：原策略 → 紧凑 |
| --- | ---: | ---: |
| help-eagerness | 5,795 → 5,908 | 6,820 → 9,154 |
| flag-default-map | 5,380 → 5,901 | 6,715 → 8,399 |
| resource-exception | 4,772 → 1,687 | 6,990 → 4,998 |
| flag-envvar | 5,944 → 5,911 | 8,577 → 8,161 |
| prompt-suffix | 5,735 → 4,105 | 7,852 → 7,018 |
| invoke-missing | 3,608 → 4,171 | 4,911 → 6,854 |
| shared-default | 5,998 → 5,951 | 6,680 → 8,116 |

压缩后有更多后续候选能装入，所以正文总长不一定下降。JSON 列只测片段列表，不含完整提示和工具 schema；它包括元数据及转义开销，不是 Token 用量。

最明确的覆盖改善是 **prompt-suffix**：

| 公开函数 | 原始非文档行数 | 候选池已覆盖 | 原策略可见 | 紧凑策略可见 |
| --- | ---: | ---: | ---: | ---: |
| prompt | 69 | 60 | 60 | 60 |
| confirm | 38 | 38 | 0 | 38 |

在相同候选池内，紧凑策略保留了 `prompt` 原有代码，并装入完整 `confirm` 非文档范围，解决本轮观察到的两函数互相挤出。`prompt` 尾部 9 行仍缺失，不能靠装填恢复。这里的非文档范围仍包含签名、空行及注释，不等于语义必要代码。

flag-envvar 的公开 `flag_value` 引用可见数量保持 9 处；invoke-missing 的运行时实现仍完整可见，缺失的重载声明没有被补入。没有明确公开名称的两个任务仍无法用名称指标判定覆盖。以上是覆盖变化，不是独立缺陷验收通过率。

## 风险与下一步

分段增加了元数据，七任务中四个的片段 JSON 变长，因此不能宣称普遍节省 Token。移除文档字符串还可能丢失行为契约；保留更多代码也不保证模型正确修复。

后续已完成 [真实补丁配对对照](staged-compact-live-v1.md)：通过独立适配层绑定额外代码哈希，原检查点不变；read-first 2/7、compact 1/7，实际 Token 19,660 / 22,788。覆盖改善未转化为修复收益，compact 不推广。下一步离线审查退化和非法补丁，不放宽校验；定位补全另做新协议，不与装填改动混在一次对照中。

## 复跑与测试

```powershell
python docs/experiments/staged_compact_packing_v1.py --source original=.tmp/real-defects/mixed-original-admission-v1 --source crossfile=.tmp/real-defects/crossfile-admission-v2 --source expansion=.tmp/real-defects/expansion-admission-v1 --output .tmp/real-defects/staged-compact-packing-v1-rerun
python -m pytest tests/test_staged_compact_packing.py tests/test_staged_evidence_coverage.py tests/test_staged_replay.py tests/test_staged_repair.py -q
```

输出须为新目录；需要保留原七份检查点和 `before` 源码。当前原始结果在 `.tmp/real-defects/staged-compact-packing-v1/packing.json`，含算法 SHA、协议及检查点 SHA、候选池身份、实际片段、逐候选装填原因和覆盖行数，被 Git 忽略。

本轮 12 项新测试及相关回归合计 **31 passed**，Ruff 通过。测试包括多函数同预算覆盖、原文与行号、重叠去重、不添加候选池外代码、文档字符串边界、原文/版本伪造拒绝、原子预算接纳、CRLF 下可见编辑与跨缺口编辑拒绝、语法错误及 Unicode。修复实现未变，未重跑全量测试。
