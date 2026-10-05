# 带契约来源的场景清单与实例化诊断

## 实现

新增可选 `--public-check-policy contract-manifest`，协议 `public-contract-feedback-v7-manifest`，旧策略及默认值保持不变。模型在同一次生成调用中返回代码和三类场景声明：shared-identifier、duplicate-before-new、persistent-replay。每项包含状态、对应测试方法、公开契约 ID、记录的标识/作用域字段及理由；契约不支持时明确 omitted，不强制虚构测试。

生成调用使用 JSON Schema；本地校验清单字段、唯一场景、引用 ID、文本边界及声明完整性。声明 implemented 需要契约来源、方法及记录字段。引用存在只证明来源可追溯，不证明模型正确解读契约。

受限 AST 诊断解析导入 API 调用中的字面记录、简单赋值和调用顺序，观察：

- 同一次调用中，或同一组命名状态参数跨调用中，同一 ID 出现在不同作用域。
- 同一次调用中，重复的作用域/ID 后还有不同记录。
- 相同命名状态跨调用，重放旧作用域/ID 并追加新记录；至少两份立即复制的 API 返回快照被断言引用。

分别保存生成代码与审查/状态过滤后的诊断；报告 shape-observed、shape-missing、unknown、method-missing-or-filtered、declared-omitted。声明存在不等于代码形状存在，形状存在也不等于期望正确。静态结果只用于诊断，不因缺少形状重写、选择检查或自动增加模型调用。

诊断追踪简单变量重绑定（包括元组赋值），避免重建状态后仍误报持久状态共享。它不是完整 Python 数据流分析：辅助函数、循环、动态对象、嵌套记录与复杂别名可能无法识别；相同命名参数也不能完全证明它们具有相同语义。正确性仍通过契约审查、实际检查执行和父进程独立验收判断。

继承 v6 的场景生成指导及 v5 的观察边界、导入限制，保留审查 Schema/算术校验、冻结检查与最多一次反馈。生成 Schema 经现有预算层计入请求开销，没有放宽工具或代码执行权限。

## 验证

新增16项测试覆盖三类正例、不同ID、批末重复、缺少快照、无关字面数据、被过滤方法、错误/重复声明、未知契约ID、显式遗漏、两阶段Schema及跨调用状态重绑定。完整回归 **475 passed、1 skipped**；Ruff、diff检查通过。

首个真实试点发现静态诊断误把跨调用的同ID用例标成缺失：代码已有同一 state/seen 上两个租户共享ID，但诊断最初只检查单次调用。修正后增加状态重绑定回归，另用新目录执行最终版本。首次原始结果保存在 `.tmp/evals/scenario-manifest-v1-pilot/summary-7bc9437ade.json`，不覆盖或混合成绩。

## 最终试点与故障拆分

最终结果为 `.tmp/evals/scenario-manifest-v1-pilot-final/summary-87412dd492.json`；run_id 为 `event-replay-1-4333ab344d`，源码哈希 `308d26d1409c18783a49c4d0106d053ab6cc3145c6d8af12c8f9ae85dc932c35`。仍使用原 localization-v1/event-replay；Qwen3.5:27b、reasoning none、temperature0，keyword K5、依赖深度2、path排序、6000字符证据、contract-coverage、输出2048、总预算30000 Token。

| 项目 | 结果 |
| --- | --- |
| 生成及审查 | 有效 |
| 三类生成/保留代码形状 | 均观察到 |
| 保留检查 | 6项，无状态过滤排除 |
| 原始缺陷代码 | 检查断言失败 |
| 修复后公开检查及独立验收 | 均通过 |
| 模型调用/反馈 | 3次 / 0次 |
| 总Token | 6,496，服务端用量完整 |

跨租户同ID用例使用同一state/seen上的两次调用；跨批次用例复制返回值快照，不再直接断言传入state。对这一份冻结生成检查作事后故障拆分，结果不进入模型请求、不挑选检查、不修改历史成绩：

| 公开契约构造的实现变体 | 冻结生成检查 |
| --- | --- |
| 原始缺陷实现 | 断言失败 |
| 正确实现 | 通过 |
| 仅保留全局ID去重错误 | 断言失败 |
| 仅保留重复记录提前停止错误 | 断言失败 |

fault-audit.json 保存检查哈希及实际执行结果；质量诊断在 `.tmp/evals/scenario-manifest-v1-quality`。这一次生成覆盖了上一版本的两个已知检出缺口，但只有一个已用于开发的合成任务试点，尚未证明重复稳定性或真实仓库泛化，也不能与不同源码版本的Token直接作效果对照。

## 复现与下一步

```powershell
python -m pytest tests/test_scenario_manifest.py -q
python -m pytest tests -q
python -m evals --suite evals/fixtures/localization-v1 --mode contract-feedback --task event-replay --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --evidence-order path --patch-policy contract-coverage --public-check-policy contract-manifest --output .tmp/evals/scenario-manifest-v1-replay
python -m evals.check_quality --input .tmp/evals/scenario-manifest-v1-replay --output .tmp/evals/scenario-manifest-v1-replay-quality
```

每次使用新目录；生成输入/Schema、场景声明、两次形状诊断、审查、Trace及验收均保存在运行目录。原始日志被Git忽略，需要另外备份。

下一步冻结共同版本，对v6/v7事件检查进行交错重复与事后故障拆分，确认三个场景的保留和检出是否稳定，同时比较调用量/Token。结果可信后停止在同一开发任务上调提示，进入真实历史缺陷开发/留出集及按需验证成本研究；不推广默认，不以隐藏验收筛选检查。
