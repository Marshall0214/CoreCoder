# 真实 Click 仓库的检索与证据预算审计 v1

## 目的与交付

检验合成任务上的检索/依赖装填方案能否用于真实源码，先确认模型实际能看到什么，再决定是否调用修复模型。

- `docs/experiments/real_retrieval_audit_v1.py`：已准入的七个 before 快照校验；BM25/Dense/Hybrid 固定查询检索；完整文件、完整文件加依赖、完整 40 行块的预算审计；结果落盘后再读取上游修复评分代理。
- `tests/test_real_retrieval_audit.py`：原始块不截断、行覆盖去重、评分后置、测试源码不进入 Embedding、输出与模型身份约束、插入修改的 before 行锚点。

本轮没有生成补丁，修复 LLM 调用为 0，也没有运行新的缺陷验收。采用历史准入结果并核验 before/after 快照摘要；不声称本轮重新通过了上游测试。

## 固定协议与隔离

七项 Click 开发任务来自原 staged-suite-v1 的 original/crossfile/expansion 三个目录，全部来自同一仓库，均已在历史实验使用，不是留出集。

检索输入仅使用 public_problem 与 before 中的公开 Python/Markdown。读取准入与目录清单后显式提取公开字段，不将 changed_source_files、after、Target、历史模型补丁或评分结果传给检索器。写入所有任务的 observations.json 后，才打开 after 源码与参考改动字段进行评分；隐藏 Target 测试文件始终不用于检索。

| 项目 | 配置 |
| --- | --- |
| 写入/检索 Python 范围 | 整个已有 src/click/*.py 包，不按参考修复文件缩小 |
| 语料 | 原 KeywordIndex：允许 Python 及公开 Markdown；排除 tests、隐藏目录及链接；不解析 RST |
| 分块 | 固定非重叠 40 行 |
| 查询 | public_problem + 字面 ` contract contracts`；三策略相同，无专属改写 |
| Embedding | qwen3-embedding:0.6b、1024 维、原文输入与精确余弦、truncate=false |
| Hybrid | 全 chunk 排名等权 RRF，常数 60 |
| 完整文件装填 | 前 5 个唯一文件；累计 6,000 字符；超限跳过，不用后续文件补位 |
| 完整文件加依赖 | 原种子保留；静态 import 最多两层；累计仍为 6,000 字符 |
| 完整块探针 | 按 chunk 排名保留最多 5 个完整块，总计 6,000 字符；超限跳过并记录实际排名；不截断 |

文件排名 Top-K 和完整块数量 K 的单位不同。完整块只是可行性探针，不是与完整文件固定文件数的消融，也不是已经接入修复 Worker 的新策略。

评分代理：参考补丁修改的源文件，以及 diff 对应的 before 修改行；插入操作采用一处相邻 before 行锚点。行覆盖按任务内修改行集合去重，再按任务取平均；含注释/文档变化，不能视为语义正确性或修复成功率。检索与装填在评分前固定，没有用这些位置调查询、排名、块边界或预算。

## 2026-10-06 实测

每个快照索引 20～43 个文件、265～392 个块。核心 core.py 为 113,869～129,928 字符，约为完整证据预算的 19～22 倍。

| 策略 | 文件 Recall@5 | 完整文件有效 Recall | 加依赖有效 Recall | 块覆盖文件 Recall | 参考修改前行覆盖率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 | 100% | 0% | 0% | 100% | 23.02% |
| Dense | 100% | 0% | 0% | 92.86% | 15.48% |
| Hybrid | 100% | 0% | 0% | 92.86% | 21.73% |

**主要阻碍是完整文件装填失效。**三种排名都把参考修改文件排进前 5，但这些大文件全部因预算被跳过；最终保留少量文档或为空，没有参考修改源码。依赖展开只从已经保留的源码出发，也无法恢复被跳过的大文件。文件 Recall@5 达到 100% 不能证明上下文足以修复。

完整块探针保留每任务 3～5 个块，实际最多 5,998 字符；可以提供源码，但定位仍不足：

| 任务 | BM25 修改前行覆盖 | Dense | Hybrid |
| --- | ---: | ---: | ---: |
| click-help-eagerness | 11.11% | 0% | 0% |
| click-flag-default-map | 0% | 0% | 0% |
| click-resource-exception | 100% | 33.33% | 100% |
| click-flag-envvar | 0% | 25% | 2.08% |
| click-prompt-suffix | 50% | 50% | 50% |
| click-invoke-missing | 0% | 0% | 0% |
| click-shared-default | 0% | 0% | 0% |

修改行命中为 0 的任务不一定完全没有相关上下文；命中 100% 也不保证模型理解行为。Dense 在本批次没有总体覆盖优势，不按单个 envvar 结果提升默认优先级。

Embedding 实测 81 次请求、1,130 条新输入、1,255 次输入缓存命中、344,852 prompt tokens，缺失用量请求为 0；请求耗时合计约 29.75 秒。缓存跨任务复用未变化的路径/块文本，Hybrid 复用 Dense 向量。用量属于共享检索构建，不重复分摊到三策略，不与修复 Token 混算；时延包含本机模型加载和调用条件，不是生产性能承诺。

```text
engine:            c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd
embedding digest: ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d
manifest:          f04e7eee5be75ef89dccbedae38759eb38042bbe8b4c1d6f553823031831ba96
audit adapter:     38d315fda00f2351cbf689b9bce732fd2c75e3dbf76ddbeebf4401d0437f49c6
observations:      095f4b7f601de2db7b4036aed23f7737a0178acb227fbf67be6c18fd63da5083
```

## 决策

保留默认引擎，不用旧完整文件协议直接运行真实补丁；目前它未提供目标源码，无法得到有意义的修复对照。

下一步复用已有 AST 符号解析和片段补丁校验，实现从本轮冻结检索候选映射到函数/方法证据的适配器。固定 6,000 字符，保留所属符号、原始行号、原文与文件哈希；先离线核验覆盖和预算，不能用参考修改位置选函数。后续片段补丁必须通过已有 apply_symbol_patch 的“old 文本出现在已提供片段”校验，不直接套用只核对文件哈希的完整文件应用器。片段装填可用后再冻结真实修复协议。

这次工作确认了迁移失败的具体位置，避免先调用修复模型再把失败归因于模型能力。结论范围限于这七个 Click 开发任务。

验证：22 项相关测试通过；全量 720 passed、1 skipped；Ruff 检查通过。所有 before 快照在检索前后摘要一致。

## 复跑与产物

corecoder 环境、项目根目录执行，输出目录必须不存在：

```powershell
python -m pytest tests/test_real_retrieval_audit.py tests/test_vector_retrieval.py tests/test_dependency_context.py -q
python -m docs.experiments.real_retrieval_audit_v1 --admission original=.tmp/real-defects/mixed-original-admission-v1/admission.json --admission crossfile=.tmp/real-defects/crossfile-admission-v2/admission.json --admission expansion=.tmp/real-defects/expansion-admission-v1/admission.json --output .tmp/real-defects/real-retrieval-audit-v1-rerun --validate-only
python -m docs.experiments.real_retrieval_audit_v1 --admission original=.tmp/real-defects/mixed-original-admission-v1/admission.json --admission crossfile=.tmp/real-defects/crossfile-admission-v2/admission.json --admission expansion=.tmp/real-defects/expansion-admission-v1/admission.json --output .tmp/real-defects/real-retrieval-audit-v1-rerun
```

`--validate-only` 核验已准入 before 与公开索引，不调用模型；其输出目录参数不会创建目录。缺失准入快照时需按既有准入流程恢复，不能以最新版仓库替代。

当前结果 `.tmp/real-defects/real-retrieval-audit-v1`：protocol.json 记录公开输入与身份，observations.json 记录评分前全部 chunk 排名和实际证据，report.json 保存后置评分、上游代理位置与 Embedding 用量。参考 after/Target 内容不进入 Embedding 请求。
