# 真实检索候选到函数证据：开发集对照 v1

## 问题与实现

上一轮真实检索审计发现：命中正确文件并不等于给模型提供可修复的源码。Click 的 core.py 超过 11 万字符，完整文件放不进 6,000 字符证据预算。本轮完成从冻结 BM25 候选到局部源码证据，再生成补丁并独立验证的闭环。

`docs/experiments/retrieved_functions_v1.py` 复用现有 AST 符号解析器，不执行被分析模块。依照冻结的 chunk 排名，选取重叠的完整函数/方法，保留装饰器、原始换行、行号和完整文件 SHA256。最多选 5 个种子，按重叠行数、函数长度、源码位置排序；重复或已包含片段跳过，过大函数回退为原始完整 chunk。然后加入一层静态可解析的本地函数依赖，总片段数不超过 20，所有证据合计不超过 6,000 字符，不截断函数。

这是一项“函数展开 + 一层依赖”的组合策略，不能把效果单独归因于 AST 或依赖展开。扫描冻结排名时可跳过不适合装填的候选，最终种子不保证全部来自排名前五。

`docs/experiments/retrieved_function_repair_v1.py` 将证据送入现有结构化补丁协议。模型每次只返回一份 edits JSON；old 必须出现在提供的单个片段内、在完整文件中唯一匹配，并通过文件版本及允许路径校验。校验失败不应用部分补丁。Target/Controls 由父进程在独立评分副本运行，参考 after 和隐藏测试不进入模型请求。

## 对照协议

七个已准入 Click 开发案例，各两组，共 14 次新修复，不复用历史补丁结果：

- **raw-chunks**：直接使用上一轮冻结 BM25 的完整 40 行 chunk 装填。
- **functions**：使用同一排名构造完整函数/方法及一层局部依赖。

两组采用相同公开需求、允许修改文件、系统提示词、单次局部补丁及独立验证协议；按任务交替组别顺序。Ollama `qwen3.5:27b`，temperature 0、reasoning none、输出上限 2,048 tokens、总预算 15,000 tokens、证据预算 6,000 字符；没有工具调用或失败后重试。配置对象保留的 max_rounds 等字段不表示本实验执行多轮 Agent。

先保存所有任务的 evidence.json 和协议摘要，再打开参考 after 计算修改前行覆盖；不按评分结果调整本轮选择策略。coverage 是上游修改位置的代理指标，不是必需修复位置的证明。所有补丁独立检查 Target 和公开 Controls，未运行完整上游测试集。

```text
engine:       c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd
repair model: 7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e
observations: 095f4b7f601de2db7b4036aed23f7737a0178acb227fbf67be6c18fd63da5083
evidence:     971a65ddee81751a5c82fc46b082fe9b76fa062aeaf04b15b4842069f16a4f8d
```

## 实测结果与失败分析

| 任务 | 原始 chunk | 函数 + 依赖 | 修改前行覆盖：chunk → 函数 |
| --- | --- | --- | --- |
| help-eagerness | failed_verification | failed_verification | 11.11% → 11.11% |
| flag-default-map | failed_verification | failed_verification | 0% → 0% |
| resource-exception | failed_verification | failed_verification | 100% → 16.67% |
| flag-envvar | invalid_patch | invalid_patch | 0% → 4.17% |
| prompt-suffix | failed_verification | failed_verification | 50% → 100% |
| invoke-missing | **passed** | failed_verification | 0% → 0% |
| shared-default | failed_verification | failed_verification | 0% → 0% |

原始 chunk 为 **1/7**，函数 + 依赖为 **0/7**，配对新增通过 0、丢失通过 1。没有 budget_exceeded、超时或执行错误；七项 before 快照在实验后摘要一致。修改前行覆盖宏平均从 23.02% 降到 18.85%，完整函数可能占用预算并挤掉其他有用位置。

| 成本（每组七次合计） | 原始 chunk | 函数 + 依赖 |
| --- | ---: | ---: |
| Prompt tokens | 15,746 | 16,367 |
| Completion tokens | 2,253 | 1,617 |
| 已计量 tokens | 17,999 | 17,984 |
| Worker 进程耗时 | 79.97 秒 | 60.62 秒 |
| 用量缺失调用 | 0 | 0 |

耗时是本机进程观测，包含启动和模型调用，不是纯推理时延；一次运行不支持稳定性能优势。复用冻结检索结果，本轮没有新增 Embedding 调用。总 Token 差仅 15，不能据此声称显著节省。每组均调用修复模型七次。

具体发现：

- **prompt-suffix**：函数组 Target 通过，但 Controls 失败。模型把输入函数的参数从单个空格改为 prompt_suffix，没有同步避免已构造提示文本中的同一后缀；正常输出变成 `Account:: alice`、`Proceed:: yes`。独立回归验证阻止了“修好新场景但破坏旧行为”的误判。
- **resource-exception**：chunk 组修改了异常传递，Target 中“资源接收到异常”通过，但“资源能够抑制异常”仍失败；函数组主要改了 close 的清理逻辑，两项 Target 都失败。位置覆盖 100% 仍不能保证补丁行为完整。
- **flag-envvar**：两组 old 包含未提供的源码，被片段校验器拒绝。保留 invalid_patch 分类，不降低约束以接受猜测的修改。
- **invoke-missing**：chunk 组通过，函数组失败，但两组上游修改行覆盖都为 0。这说明代理位置没有覆盖所有有效修复路径，不能用它替代 Target/Controls 成败。

## 决策与下一步

保持默认引擎和已有策略；函数适配器作为可复跑实验保留，不升级为默认。结果限于七个开发案例的每组一次运行，尚无留出集验证或重复实验，不能泛化为“函数上下文一定更差”。

这轮完成了可用源码证据到真实补丁、独立验证的完整对照，并将瓶颈从“完整文件装不下”进一步定位到候选排序与行为完整性。下一步先做**直接按函数/方法建立 BM25 索引的离线审计**，对比当前“40 行块排名后按重叠展开”的证据选择；基于公开需求设计规则，保留原始 chunk 对照，不按这七个参考修改位置调参。候选覆盖与预算约束合格后，再冻结修复实验，并建立未参与策略设计的留出任务。

验证：新适配器测试 5 passed；全量 **725 passed、1 skipped**；新增文件 Ruff 检查通过。冻结 corecoder/evals 引擎未修改。

## 复跑与产物

依赖上一轮冻结检索观察和准入 before/after 快照；不能用仓库最新版替代。输出目录必须不存在。在 corecoder 环境、项目根目录执行：

```powershell
python -m pytest tests/test_retrieved_functions.py -q
python -m docs.experiments.retrieved_function_repair_v1 --source .tmp/real-defects/real-retrieval-audit-v1 --output .tmp/real-defects/retrieved-functions-rerun-audit --audit-only
python -m docs.experiments.retrieved_function_repair_v1 --source .tmp/real-defects/real-retrieval-audit-v1 --output .tmp/real-defects/retrieved-function-repair-rerun
```

`--audit-only` 不调用修复或 Embedding 模型。实际修复产物在 `.tmp/real-defects/retrieved-function-repair-v1`：protocol.json 固定身份与调用配置，evidence.json 保存评分前证据，coverage.json 保存后置位置覆盖，experiment.json 保存全部状态、用量和验证；每个任务/策略目录保留响应、Trace、补丁与验证日志。`.tmp` 被 Git 忽略，提交本报告和适配器，原始结果需另行归档。
