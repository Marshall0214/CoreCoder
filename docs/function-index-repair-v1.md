# Python 行块与直接函数种子：真实修复对照 v1

## 目的与实现

上一轮离线审计在同 Python 语料下，将参考修改行覆盖宏平均从 23.02% 提高到 37.90%。本轮检验位置覆盖改善能否转化为通过独立行为验证的补丁。

新增 `docs/experiments/function_index_repair_v1.py`，复用已有单次片段补丁 Worker 和独立验证器。从冻结审计 observations 读取证据，不重新检索、不修改查询和排序；两个策略各重新运行七个已准入 Click 开发任务，共 14 次新修复。

- **python-line-chunks**：Python 语料的完整 40 行块，预算内最多五个。
- **direct-functions**：同一 Python 文件集合的完整函数/方法种子，预算内最多五个，不加依赖，不回退局部窗口。

两组使用相同公开需求、允许文件、系统提示、单次 edits JSON、预算、模型和独立评分。按任务交替组别顺序。证据内容、行号和完整文件哈希在复制前后核验；old 必须出现在提供的单个片段中，并在完整文件唯一匹配，所有编辑校验通过才应用。模型请求仅含公开需求、允许路径和证据，不含 after、参考修改位置或 Target 内容。

所有准入任务在模型调用前检查：before 的 Target 断言失败、Controls 通过，排除环境执行错误。修复后在独立副本检查 Target 与公开 Controls。只有补丁合法、目标通过且回归通过才算成功；没有执行完整上游测试集。

Ollama `qwen3.5:27b`，temperature 0、reasoning none、输出上限 2,048 tokens、总预算 15,000 tokens、证据预算 6,000 字符、上下文窗口配置 16,000 tokens、Worker 墙钟上限 600 秒、模型请求超时 60 秒、验证超时 15 秒。每分支仅一次模型请求、无工具调用、无反馈重试；共享配置中的 max_rounds 等字段不表示本实验运行多轮 Agent。

## 实测结果

| 任务 | Python 行块 | 直接函数 |
| --- | --- | --- |
| help-eagerness | failed_verification | failed_verification |
| flag-default-map | failed_verification | failed_verification |
| resource-exception | failed_verification | failed_verification |
| flag-envvar | invalid_patch | failed_verification |
| prompt-suffix | failed_verification | failed_verification |
| invoke-missing | invalid_patch | **passed** |
| shared-default | failed_verification | failed_verification |

Python 行块 **0/7**，直接函数 **1/7**；配对新增通过 1、丢失通过 0。两组各调用修复模型七次，没有 budget_exceeded、超时或验证执行错误。七项准入 before 在实验后摘要一致。

| 每组七次合计 | Python 行块 | 直接函数 |
| --- | ---: | ---: |
| Prompt tokens | 15,716 | 14,817 |
| Completion tokens | 1,703 | 2,198 |
| 已计量总 tokens | 17,419 | 17,015 |
| Worker 进程耗时 | 64.60 秒 | 70.37 秒 |
| 缺失用量调用 / 缺失 metrics 分支 | 0 / 0 | 0 / 0 |

函数组总 Token 少 404，但输出 Token 更多，Worker 耗时更长。耗时包含进程启动与模型调用，是本机观测；每组只有一次运行，不支持稳定节省或加速结论。本轮无新增 Embedding 调用。

## 具体成功与失败

- **invoke-missing**：函数组在 Context.invoke 的完整证据中，将缺省值 UNSET 转为 None 后再执行 type_cast_value，Target 和 Controls 均通过。行块组尝试修改未提供的 old 文本，被补丁范围校验拒绝。这是完整函数证据转化为真实成功的一个开发案例。
- **resource-exception**：函数组传递了异常类型、实例及回溯，资源接收异常的子场景通过；没有将资源抑制异常的返回值传回上下文退出流程，抑制异常子场景仍失败。源码包含 close 和 __exit__，失败不能只解释成缺少这些函数。
- **help-eagerness**：函数组直接反转 is_eager 排序，没有建立 help 与其他 eager callback 的优先级；Target 仍看不到预期帮助输出。命中参数处理函数不保证修改方向正确。
- **prompt-suffix**：函数组在 _build_prompt 返回值上加 rstrip，Controls 通过，但没有消除空后缀时输入函数额外添加的空格，prompt/confirm 两个 Target 子场景均失败。行块组 Target 和 Controls 都失败。
- **flag-envvar**：行块补丁越过证据范围被拒绝；函数组修改 split_envvar_value 后仍未解决 Target 行为。合法补丁只是工程约束通过，不等于修复成功。

## 决策与下一步

固定协议的三轮新重复已完成，见 [function-index-repair-repeat-v1.md](function-index-repair-repeat-v1.md)：行块 0/21、函数 3/21，全部成功来自 invoke-missing 的 3/3 复现。Prompt 和状态分类三轮一致；下一步扩充未参与设计的真实准入任务。

保留默认引擎，将直接函数种子作为实验候选，尚不提升为默认。此前含 Markdown 的原始 chunk 曾通过 1/7，但语料和提示证据不同，不与本轮 0/7 拼接为同一对照。本轮能报告的是同 Python 语料、固定单次补丁协议下的一次配对结果。

下一步为本轮固定协议增加重复运行与配对汇总，确认 invoke-missing 的收益及其余失败是否稳定；不按本轮 Target/after 反馈改写提示或证据后再声称同一对照。随后扩充未参与设计的真实准入任务，检验泛化。已知失败涉及检索缺口和行为契约遗漏，重复结果稳定后再决定优化哪个环节。

限制：七个 Click 开发案例已用于策略选择，没有留出集；每组一次运行，不报告统计显著性或普遍提升。验证只覆盖 Target 与公开 Controls，不能声称完整上游回归或生产可靠性。

验证：新增测试 **6 passed**，覆盖原文及版本校验、范围和预算、冻结观察、缺失用量、完整配对运行与证据篡改；全量 **738 passed、1 skipped**，新增文件 Ruff 通过。

## 身份与复跑

```text
engine:       c53960d2ff6efe5ec91a836a3a8d47f1475d4a957071fab0261e0176eb89d6dd
repair model: 7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e
observations: d2367ad4330c4b83fe9921482fba4043e6640bbec521daad5dde88defb7b7479
evidence:     6380da2dcc0d0b64ff5f48c30cb1c380ef4476cd6a78008407687f123eaf3145
new runner:   97d6d3af30723894b49ee0ff340ba8bb34b25b18839d728e6c7546df0d9d0aac
```

产物目录 `.tmp/real-defects/function-index-repair-v1`：protocol.json 固定配置、顺序和实现摘要；evidence.json 保存两组全部证据；experiment.json 增量保留所有分支的状态、验证和用量。每任务/策略目录保留响应、Trace、补丁、Worker 日志和独立验证日志。用量缺失不当作零成本，未完成运行不当作完整结果。

corecoder 环境、项目根目录执行；需已准入快照、冻结审计观察和相同模型，输出目录必须不存在：

```powershell
python -m pytest tests/test_function_index_repair.py -q
python -m docs.experiments.function_index_repair_v1 --source .tmp/real-defects/function-index-audit-v1-corpus-control --output .tmp/real-defects/function-index-repair-rerun
```

`.tmp` 不入 Git，提交运行器、测试与本报告，原始产物另行归档。
