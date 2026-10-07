# 候选运行时异常反馈 v1

## 核心改动

此前公开检查同时出现断言失败和执行错误时，统一流程直接停止反馈。源码契约上下文实验的 none-salt 就因此只运行了一次。本轮新增 [结构化观察器](experiments/runtime_observation_v1.py)，通过 unittest Result 记录测试、异常类型、消息及 traceback 位置，区分候选源码异常与检查/环境故障。

- `assertion_failure`：有效断言失败，维持已有反馈行为。
- `candidate_runtime_error`：异常末尾帧明确位于候选源码；可以与断言失败共存，使用已有的一次反馈机会。
- 检查代码或来源不明的异常、发现/导入故障、超时、零测试、跳过或不完整报告：停止，不据此修改代码。

归因采用保守规则：异常末尾帧落入外部依赖时记为未知，即使它可能由候选参数导致，也不会自动反馈。框架将异常转换成断言失败时，仍按断言处理。它不是通用因果诊断或针对恶意源码的安全边界。

观察器使用隔离 Python 与凭据白名单环境，复制候选源码运行不可变的公开检查，检测源码和检查文件变化；不读取私有 Target/Controls。原始 stdout/stderr 与 observation.json 保存供核查。反馈仅提供公开测试信息，结构化摘要最多五个问题、每条消息 500 字符与八个栈帧，不包含局部变量。

[反馈 Worker](experiments/runtime_feedback_worker_v1.py) 在原始缺陷仍有效复现的前提下，允许候选运行异常进入公开反馈；检查故障不会获得额外机会。最多两次模型请求，共用 15,000 Token，第二次仍失败就停止，独立验收不变。默认 API 和冻结引擎未修改。

## 离线与对照协议

零模型调用重放上一轮失败源码：原缺陷为有效断言失败、失败候选为 candidate_runtime_error、正确修复示例通过。观察器认证位于 `.tmp/real-defects/runtime-observation-audit-v1/audit.json`。

[新对照入口](experiments/runtime_feedback_compare_v1.py) 重新运行六项已查看任务，每项两组各一次：

- `assertion-only`：原门槛，只对无执行错误的断言失败提供反馈。
- `runtime-feedback`：额外允许可归因的候选异常，并提供结构化问题摘要。

两组都使用新的结构化公开测试执行器；只有反馈门槛及候选异常的反馈内容不同。两组同用固定 Qwen、非流式适配器、关闭思考、temperature=0、top_p=1、输出 2,048、上下文预检查 16,000、同样的事务保护和评分。none-salt 两组都启用冻结源码契约上下文，其余五项保持原检索。没有切换 DeepSeek、增加预算或重试，也没有同时加入“保留已编辑函数”策略。

六对初始提示与回答都相同。原始源码、公开检查、上下文提取器、模型身份与独立评分均校验哈希；私有评分仅在最终父进程中执行，不用于模型反馈。四项没有认证公开检查的任务维持原流程，不补造公开反馈。

## 实测结果

| 任务 | 仅断言反馈 | 运行时反馈 |
| --- | --- | --- |
| click-usage-empty | 通过 | 通过 |
| click-echo-empty-bytes | 通过 | 通过 |
| click-style-color-validation | 通过 | 通过 |
| itsdangerous-none-salt | Target / Controls 失败 | Target / Controls 失败 |
| itsdangerous-future-age | 通过 | 通过 |
| itsdangerous-malformed-time | 通过 | 通过 |

| 指标 | 仅断言反馈 | 运行时反馈 |
| --- | --- | --- |
| 独立验收 | 5/6 | 5/6 |
| 请求 | 7 | 8 |
| Prompt Token | 17,068 | 23,717 |
| Completion Token | 3,325 | 3,489 |
| 总 Token | 20,393 | 27,206 |
| Worker 总秒数 | 103.28 | 116.66 |

共 **15 次本地 Qwen 请求、47,599 Token、0 次 DeepSeek 请求**。响应均正常结束，无预算停止或输出截断。新规则在 none-salt 确实触发第二次请求；该任务公开检查的运行异常由 **8 个降至 0 个**，最终仍有 **12 个断言失败**。这些是公开检查的问题记录，包括 subtest，不是不同缺陷数。

模型补上 Signer 的 None 默认处理，却把 Serializer 的显式 None 错误改成 Serializer 默认盐值，并保留第一轮删除的参数回退。因此 Signer(None) 的独立目标通过，Serializer 的 None 区别及 wrong-salt 回归仍失败。不能按部分目标或异常消失计为修复成功。

运行时反馈总 Token 增加约 **33.4%**，来自额外一次请求。本轮证明观察—反馈路径能够处理这种异常，**没有证明最终修复率或成本改善**。单轮、小样本、此前已查看任务，不是泛化评测；耗时也不作为稳定性能比例。

## 剩余问题与决策

第一轮实际编辑了 `Serializer.make_signer` 和 `Serializer.iter_unsigners`。删除参数回退后，这两个函数不再匹配已有的“参数、实例状态与转发同时出现”检索规则，第二轮完整证据变成构造函数、JWS 构造函数和 unsign。两函数仍出现在 AST 摘要中，但完整可编辑片段不再提供。

唯一匹配编辑器要求 old 文本来自实际提供的片段，所以摘要不足以替代编辑原文。这个丢失可以从 initial-context.json 与 feedback-context.json 直接核查；它是下一步值得验证的上下文问题，不能据此断言它是语义失败的唯一原因。

**决策：保留运行异常观察与有界反馈为可选能力，冻结本轮，不替换默认。下一步优先保留已编辑函数的当前版本原文，再单独验证修复效果。** 不继续通过增大 Token 或增加调用次数掩盖证据缺口。

## 验收与复跑

新增 **21 项**测试，覆盖真实候选 TypeError/AttributeError、检查代码异常、混合失败、subtest、发现故障、源码修改检测和停止分类；反馈测试验证一次修正、当前版本片段与累计预算。加上原上下文和统一流程专项 **47 passed（3.23 秒）**；最终 Windows **1,044 passed、2 skipped（179.34 秒）**，Ruff 通过。

机器摘要：[runtime-feedback-v1.json](runtime-feedback-v1.json)。本轮未重跑 Linux、Docker、HTTP，不覆盖历史验收记录。原始完整记录位于 `.tmp/real-defects/runtime-feedback-compare-v1`，不进 Git。

```powershell
$env:TEMP='D:\project_other\CoreCoder\.tmp\python-temp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
python -B -m pytest tests/test_runtime_observation.py -q -p no:cacheprovider --basetemp .tmp/pytest-runtime-user
python -B -m docs.experiments.runtime_feedback_compare_v1 --audit-only --output .tmp/real-defects/runtime-observation-audit-user
python -B -m docs.experiments.runtime_feedback_compare_v1 --output .tmp/real-defects/runtime-feedback-user
```

真实入口读取固定的 runtime-observation-audit-v1 认证。新的离线输出用于核查，不覆盖旧认证；修改观察器需重新立版本及认证入口。真实复跑还需要冻结准入快照、隔离 Python、公开认证、历史失败源码和固定 Qwen，单元测试不需要模型。所有新增产物放 D 盘。
