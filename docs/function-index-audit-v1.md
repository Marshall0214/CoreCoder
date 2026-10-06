# 函数级 BM25：七个真实任务的离线审计

## 本轮完成的工作

复用 `evals/symbol_index.py` 的 AST 符号索引与现有 BM25 评分，在实验适配器 `docs/experiments/function_index_audit_v1.py` 中直接按完整函数/方法检索。没有新增默认工具、修改冻结引擎或调用模型。

原方案先检索 40 行块，再按源码重叠展开函数；新方案先构建完整函数语料，再计算 BM25。保留装饰器、原始换行、行号、符号名及完整文件 SHA256。排序按分数、路径、行号确定；选择最多五个预算内种子，跳过过大函数和重叠片段，不截断函数，不添加窗口回退。另设一层本地函数依赖组，总片段数上限 20，证据总预算固定 6,000 字符。依赖发现不执行模块。

完整排名、装填证据与丢弃原因先对所有任务保存，再打开 after 计算参考修改前行覆盖。选择器只接收公开描述和允许源码；查询保持 `public_problem + contract contracts`，没有增加任务专用词或按参考路径指定函数。七项 before 快照评分后摘要一致。

## 语料控制与结果

旧 chunk 索引包含允许 Python 源码及 Markdown；新函数索引只包含 Python。因此补充同一 Python 文件语料的 40 行块对照，核对其 source_hash 与函数索引一致。初次四组审计保留在 `.tmp/real-defects/function-index-audit-v1`；补全语料控制后的五组结果另存 `.tmp/real-defects/function-index-audit-v1-corpus-control`，未覆盖旧报告，也未据评分改变查询、排序或装填规则。

| 策略 | 参考修改行覆盖宏平均 | 目标文件覆盖宏平均 | 平均证据字符 |
| --- | ---: | ---: | ---: |
| 原始 chunk（含 Markdown 语料） | 23.02% | 100% | 5,974 |
| 原始块排名后展开函数及依赖 | 18.85% | 100% | 5,639 |
| 仅 Python 的完整 40 行块 | 23.02% | 92.86% | 5,913 |
| 直接函数检索，仅种子 | **37.90%** | 100% | 5,137 |
| 直接函数检索，加一层依赖 | **37.90%** | 100% | 5,341 |

| 任务 | Python 行块 | 直接函数 | 块展开函数 |
| --- | ---: | ---: | ---: |
| help-eagerness | 11.11% | 44.44% | 11.11% |
| flag-default-map | 0% | 0% | 0% |
| resource-exception | 100% | 66.67% | 16.67% |
| flag-envvar | 0% | 4.17% | 4.17% |
| prompt-suffix | 50% | 50% | 100% |
| invoke-missing | 0% | 100% | 0% |
| shared-default | 0% | 0% | 0% |

相对同 Python 语料行块，直接函数组宏平均提高 **14.88 个百分点**，三项提高、一项降低、三项持平。它在 invoke-missing 返回 Context.invoke 完整实现，在 help-eagerness 返回参数处理顺序函数；resource-exception 相对行块回退，prompt-suffix 相对旧块展开方案回退。收益不是所有任务普遍改善。

依赖组未提高任何任务的参考修改行覆盖，平均多占约 203 字符。本轮不支持继续增加依赖深度。flag-default-map、shared-default 仍为 0；flag-envvar 覆盖很低，公开描述驱动的词匹配仍有缺口。invoke-missing 为凑齐五个预算内种子扫描到排名 120，因此最多五个种子不等于仅查看排名前五；低分补位也是后续需要审查的风险。

## 结论与下一步

后续真实修复对照已完成，见 [function-index-repair-v1.md](function-index-repair-v1.md)：Python 行块通过 0/7，直接函数种子通过 1/7，新增成功为 invoke-missing。尚未重复运行或验证留出集。

结果足以把**直接函数检索、仅种子**作为下一轮开发对照候选；依赖组没有位置覆盖增益，暂不作为首选。这个选择是开发集上的后置决策，下一轮必须冻结证据与协议，保留对照，不把七项任务当留出集。

下一步用相同模型、单次片段补丁、预算及 Target/Controls，比较仅 Python 行块与直接函数种子的真实修复结果，两组都重新运行，不沿用旧补丁。将此结果与此前含 Markdown 的 chunk 修复结果分开，不能拼接为同一公平对照。随后扩充未参与策略设计的准入任务，再检验能否泛化。

本轮修复调用和 Embedding 调用均为 **0**，没有修复成功率、模型 Token 或推理时延结论。覆盖来自上游参考修改位置，可能遗漏等价修复；上一轮 invoke-missing 的有效补丁覆盖为 0，已证明该指标不能替代行为验证。函数组也省略模块常量、类头部等非函数代码，对无法解析源码不建函数条目；这些变化意味着对照并非只改变分块尺寸。

## 身份、验证与复跑

```text
engine:             c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd
source observations:095f4b7f601de2db7b4036aed23f7737a0178acb227fbf67be6c18fd63da5083
new observations:   d2367ad4330c4b83fe9921482fba4043e6640bbec521daad5dde88defb7b7479
audit adapter:      abba3339be8838c68693aad344fc106b44e36201d0db1cffdc44f6a6637630a7
reused symbol index:4b80a3c5a3202adf142ec214da038d791636b27ed6286db0b79ed09d912155e6
```

新增 7 项测试覆盖原文与版本、隐藏语料隔离、确定排序、索引过程源文件变化、解析失败、超大函数、重叠去重、依赖深度与预算，以及所有证据先于评分落盘。全量 732 passed、1 skipped；补充语料控制后相关测试 12 passed、Ruff 通过。

corecoder 环境、项目根目录执行，输出目录必须不存在：

```powershell
python -m pytest tests/test_function_index_audit.py tests/test_retrieved_functions.py -q
python -m docs.experiments.function_index_audit_v1 --source .tmp/real-defects/real-retrieval-audit-v1 --output .tmp/real-defects/function-index-audit-rerun
```

依赖已准入快照和冻结 observations，不能以最新版 Click 替代。protocol.json 记录身份与公开输入；observations.json 保存评分前完整排名、证据和丢弃原因；report.json 保存后置覆盖。`.tmp` 不入 Git，原始产物须另行归档。
