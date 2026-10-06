# 固定预算下的公开依赖补齐 v1

## 问题与实现

三轮复测中，模型在未提供辅助模块源码时猜测其实现，出现空 old 或错误行为。检验假设：在同一检索排名和证据预算下补齐公开依赖，是否减少此类失败？源码缺失只是可能原因，不预设补齐必然提高成功率。

- `docs/experiments/dependency_context_v1.py`：复用 `evals.pipeline.local_imports` 的 Python AST 静态 import 解析；在完整原文种子之后追加最多两层本地依赖。不 import、不执行仓库代码。
- `docs/experiments/dependency_repair_v1.py`：先保存无评分标签的证据审计及冻结协议，再执行全新 2×2 对照，复用既有补丁 Worker 与独立 verifier。
- `tests/test_dependency_context.py`：验证两层深度、循环去重、相对导入、允许列表、字符预算、原文及版本一致性、完整矩阵与收益/回退统计。

只使用索引中当前版本的允许 Python 文件，补齐顺序为确定性的广度优先。保留所有已选种子及其顺序，依赖在后追加。总字符不超过 6,000、文件数最多 20；超限跳过并记录，不截断，不从隐藏测试或参考修复获取线索。被预算排除的种子不用于展开依赖。动态 import、调用关系和外部库实现不在本协议范围内。

原始种子的 Top-K=5 不变；依赖展开后实际证据文件数允许大于 5。因而本轮隔离的是“相同字符上限内增加公开依赖内容”的效果，不是固定实际证据文件数的对照。

## 冻结设计

11 个原合成开发任务，四组各运行一次，共 44 个新补丁：

| 检索排名 | 原始证据 | 加公开依赖 |
| --- | --- | --- |
| BM25 | bm25-seeds | bm25-imports |
| Dense | dense-seeds | dense-imports |

全部复用既有评分前 observations 排名；Embedding 新调用为 0。沿用 qwen3.5:27b、temperature=0、reasoning_effort=none、修复预算 15,000 Token、context 16,000、输出 2,048、进程 600 秒及单项测试 15 秒。Prompt、精确唯一 old/new 替换约束、Worker 和独立验证器不变；没有反馈轮次，不放宽空 old 或未提供源码的修改权限。

四组顺序随任务轮换。所有结果来自本轮全新调用，前轮通过率不混入分母。模型调用前保存协议、全部证据内容及摘要；每分支前核对引擎、四份适配器、模型、语料、清单与评分器身份。未完成或缺失/重复分支的矩阵不能用于最终分析。

## 评分前证据审计

2026-10-06，在读取任何评分标签之前完成 11×4 证据构造：

| 任务 | BM25 新增依赖 | Dense 新增依赖 |
| --- | --- | --- |
| falsey-overrides | defaults.py | 无 |
| inclusive-date | date_utils.py | 无 |
| retry-policy | 无 | 无 |
| tenant-cache | 无 | 无 |
| timeout-units | 无 | 无 |
| artifact-routing | routing.py、matching.py | matching.py、paths.py |
| checkout-rounding | pricing.py | pricing.py |
| event-replay | event_keys.py | event_keys.py |
| job-deadline | execution.py、budget.py、retry.py | 无 |
| pagination-cursor | paging.py、cursor_codec.py、query.py | cursor_codec.py |
| lease-lifecycle | models.py、lookup.py、expiry.py | lookup.py、models.py |

所有展开结果均在原 6,000 字符上限内，最大 2,078 字符，本批次没有预算丢弃项。Dense 的部分依赖已经在种子里，不重复添加。部分分支的两种策略输入相同；须结合相同 Prompt 下的输出波动解释成绩，不能把每个变动自动归因于新增依赖。

冻结摘要：

```text
engine:              c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd
repair model:        7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e
observations:        a3dcd8c4b4dba89573cf0c0ccbe0463ab06a74e0faf8ef3b41e7e01ef8561cbb
evidence audit:      e2a49f18282fc40c9d9585f621d2389777577a6c717dd974061c761d29005e24
dependency adapter:  44e7ad7bbe0b7d8281b24ccb4ad96914cbfeeb50b2e5fb3045fa3cdcd3ee0834
experiment adapter:  163174b42c3604e0fffe524a46dffc13efa79cb6b3b7b2fe834331e9d70928d8
```

## 2026-10-06 实测与判断

44 个新分支全部完成，均经过独立目标与回归测试；44 次修复模型调用、40,577 修复 Token，用量无缺失。没有预算停止、超时或基础设施错误，新增 Embedding 调用为 0。

| 策略 | 通过 | 成功率 | 修复 Token | 无效补丁 | 应用后验证失败 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BM25 原始证据 | 4/11 | 36.36% | 9,284 | 3 | 4 |
| BM25 加依赖 | 6/11 | 54.55% | 10,235 | 0 | 5 |
| Dense 原始证据 | 5/11 | 45.45% | 10,159 | 1 | 5 |
| Dense 加依赖 | 5/11 | 45.45% | 10,899 | 0 | 6 |

| 任务 | BM25 原始 | BM25 加依赖 | Dense 原始 | Dense 加依赖 |
| --- | --- | --- | --- | --- |
| falsey-overrides | 通过 | 通过 | 通过 | 通过 |
| inclusive-date | 验证失败 | 验证失败 | 验证失败 | 验证失败 |
| retry-policy | 通过 | 通过 | 通过 | 通过 |
| tenant-cache | 通过 | 通过 | 通过 | 通过 |
| timeout-units | 通过 | 通过 | 通过 | 通过 |
| artifact-routing | 验证失败 | 验证失败 | 验证失败 | 验证失败 |
| checkout-rounding | 无效补丁 | 通过 | 无效补丁 | 通过 |
| event-replay | 验证失败 | 验证失败 | 验证失败 | 验证失败 |
| job-deadline | 无效补丁 | 验证失败 | 验证失败 | 验证失败 |
| pagination-cursor | 无效补丁 | 验证失败 | 通过 | 验证失败 |
| lease-lifecycle | 验证失败 | 通过 | 验证失败 | 验证失败 |

依赖补齐的配对观察：BM25 两项新增成功、零回退；Dense 一项新增成功、一项回退。BM25 多用 951 Token（10.24%），Dense 多用 740 Token（7.28%）。补齐组没有无效补丁，但合法补丁仍可能遗漏行为，不能把“格式与作用域合法”当作“修复正确”。

具体案例：

- **checkout-rounding：两种检索均获益。**补入 pricing.py 后，模型在 pricing.py 和 fees.py 同时使用 ROUND_HALF_UP 修复金额取整，独立验证通过；原始组都生成空 old 被拒绝。
- **lease-lifecycle：BM25 获益，Dense 未获益。**BM25 种子含 cleanup.py，其公开 import 解析补入 expiry.py；补丁修复 acquire.py、expiry.py、lookup.py、renew.py 的时间单位、边界和租户行为，独立验证通过。Dense 种子缺 cleanup.py，仅补入 lookup.py/models.py，无法沿其 import 找到 expiry.py。依赖展开不能补偿所有起始种子遗漏。
- **pagination-cursor：Dense 回退。**原始组这次修复 query.py 与 paging.py 并通过；加依赖组只修改 query.py，漏改游标推进逻辑，目标测试失败。更多源码没有保证模型完整执行所有修复。
- **inclusive-date、event-replay、job-deadline 等仍失败。**补入辅助模块后仍存在语义修复问题，说明单纯增加依赖信息不是完整解法。

上述差异来自单轮开发集观察，不是稳定提升证明；此前已观察到相同 Prompt 的输出波动。本批次 retry-policy、tenant-cache、timeout-units 的 seeds/imports 输入相同，Dense 另外三项也没有新增依赖，未将它们作为新增源码收益案例。评分前审计与真实修复结果分开保存，不使用隐藏测试选择补齐文件。

决策：保留“BM25 + 公开依赖补齐”为实验候选，默认引擎和检索策略不变；Dense 本轮没有净增成功，不推广组合。合成集已提供正负案例，不继续围绕这些任务调 Prompt 或展开深度。下一步迁移到已准入的真实 Click 缺陷，先做公开代码检索与证据预算的离线可行性审计；真实源文件较大，必须先判断完整文件装填是否可用，再冻结修复协议。正式结论仍需要真实仓库、留出任务与重复验证。

验证：18 项相关测试通过；全量 715 passed、1 skipped；Ruff 通过。旧协议、Worker、原始评分器与冻结引擎未修改。

## 复跑

在项目根目录 corecoder 环境中执行，输出目录必须不存在：

```powershell
python -m pytest tests/test_dependency_context.py tests/test_vector_repair.py tests/test_vector_repair_repeat.py -q
python -m docs.experiments.dependency_repair_v1 --source .tmp/retrieval/vector-repair-v1 --output .tmp/retrieval/dependency-context-v1-audit-rerun --audit-only
python -m docs.experiments.dependency_repair_v1 --source .tmp/retrieval/vector-repair-v1 --output .tmp/retrieval/dependency-repair-v1-rerun
```

source 的构造见 [单次补丁协议](vector-repair-v1.md)。`--audit-only` 不调用生成或 Embedding 模型，但检查本地修复模型身份并写入公开证据审计。当前最终审计 `.tmp/retrieval/dependency-context-v1-final-audit`；修复批次 `.tmp/retrieval/dependency-repair-v1`。早期接线审计 `.tmp/retrieval/dependency-context-v1-audit` 不用于最终统计。

批次 protocol.json 保存冻结协议；evidence-audit.json 保存模型调用前的公开证据；experiment.json 增量保存原始运行；matrix.json 在 44 格完整后统计。每项 `repeat-1/task/policy` 目录保存响应、Trace、补丁与独立目标/回归日志。中断批次保留 complete=false，不自动追加旧成绩。
