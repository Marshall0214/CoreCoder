# Qwen / DeepSeek 固定流程对照 v1

## 目的与实现

检验此前持续失败的 `itsdangerous-none-salt` 是否能在相同修复流程下由另一模型解决。新增 [对照入口](experiments/provider_compare_v1.py) 与 [适配器](experiments/provider_compare_worker_v1.py)，重新运行两组，不把历史 Qwen 结果作为本轮对照。

复用冻结的统一反馈流程：相同初始 AST 函数证据、允许文件、唯一文本匹配编辑、事务保护、公开反馈与独立 Target/Controls。每分支最多两次模型请求，共享 15,000 Token 预算，输出上限 2,048；证据最多五个函数、6,000 字符，执行器预检查上下文上限 16,000。四项没有认证公开检查的任务不使用独立评分生成反馈。

两组通过相同 OpenAI 兼容 SDK 使用非流式请求，temperature=0、top_p=1、单请求超时 60 秒、SDK 自动重试为零，任务执行超时 600 秒。六项各运行一次，交替执行顺序。不同供应商的分词器、模型、推理服务和缓存实现仍不同；这是模型/服务配置对照，不能把结果全部归因于模型架构。16,000 是执行器估算限制，不代表已设置两家服务器的原生上下文大小。

- Qwen：Ollama `qwen3.5:27b`，`reasoning_effort=none`，冻结模型摘要与 Ollama 身份。
- DeepSeek：`deepseek-flash`，显式 `thinking.type=disabled`。API Key 只从项目 `.env` 或同名环境变量 `DEEPSEEK_API_KEY` 读取，不选择其他供应商的密钥，不保存进任务或请求文件。

关闭思考与参数语义依据 [DeepSeek 思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode/)、[Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/) 和 [Ollama OpenAI 兼容说明](https://docs.ollama.com/api/openai-compatibility)。DeepSeek 非思考模式的 top_p 固定为 1，因此本轮 Qwen 也明确请求 1。

适配器记录返回模型、服务指纹、finish reason、用量、缓存用量及是否出现思考字段。截断、空回答、意外思考内容或模型别名不符的输出停止，不交给编辑器；已返回用量仍记入预算。缺少用量按既有保守预留处理；失败供应商请求的实际用量记为未知。不会保存原始思考文本。

## 结果

| 任务 | Qwen | DeepSeek |
| --- | --- | --- |
| click-usage-empty | 通过 | 通过 |
| click-echo-empty-bytes | 通过 | 通过 |
| click-style-color-validation | 通过 | 通过 |
| itsdangerous-none-salt | 失败 | 失败 |
| itsdangerous-future-age | 通过 | 通过 |
| itsdangerous-malformed-time | 通过 | 通过 |

| 指标 | Qwen | DeepSeek |
| --- | --- | --- |
| 独立验收 | 5/6 | 5/6 |
| 模型请求 | 8 | 8 |
| Prompt Token | 21,579 | 22,087 |
| Completion Token | 3,834 | 1,894 |
| 总 Token | 25,413 | 23,981 |
| Worker 总耗时 | 119.53 秒 | 25.47 秒 |
| 事务拒绝 | 0 | 0 |

本轮共 16 次新请求，49,394 Token；两组六对初始提示哈希相同，所有响应均返回 `stop`，没有预算停止、截断或意外思考字段。两家均未提供 reasoning token 明细，记录为未知，不能声称测得 reasoning tokens=0。DeepSeek 八次服务指纹均为 `aeb56401ca74e127821c4f9126dcb669`，缓存命中 Token 为 0、未命中为 22,087；云端别名与指纹不能替代不可变模型权重摘要。

DeepSeek 本轮总 Token 比 Qwen 少约 5.6%，Worker 耗时更短，但这只是一次本机/云端观测，不能当作稳定速度比或美元成本比较。Token 预算是估算预检查加返回用量约束，不是供应商账单硬上限。

## none-salt 的具体失败

两组均用了一次公开断言反馈，最终补丁通过语法、重复定义和模块加载检查，但公开检查和独立 Target 仍失败，Controls 均通过。

- DeepSeek 在 `Signer.__init__` 引用不存在的 `self.default_salt`；导入模块成功，真正构造 `Signer(salt=None)` 时才抛出 `AttributeError`。
- Qwen 修好了 `Signer(None)`，却改动 Serializer 默认盐值及方法级参数转发，导致同一 Serializer 的 dumps/loads 盐值不一致，抛出 `BadSignature`。

这说明结构有效、模块可加载并不保证参数关系正确，也不能据此宣称保护机制避免了功能回归。本轮仅证明在当前证据和反馈下，两种模型都没有解决该任务。

**决策：冻结本轮，不替换默认服务，不增加重试。** 后续若继续优化，先离线检查上下文是否包含默认值、成员定义和参数转发的必要契约，再单独比较契约证据组织策略。此次没有足够证据把瓶颈单独归因于模型或检索。

六项均此前已查看、仅一次运行，不是未见任务泛化评测，也不是与 Codex/Claude Code 的能力比较。通过指满足独立 Target/Controls 与修改约束，不代表完整上游测试通过。

## 验收与复跑

新增适配器测试 **14 passed**，覆盖关闭思考、用量记账、异常输出拒绝、无自动重试、密钥选择及 worker 配置副本。最终 Windows 全量 **1,013 passed、2 skipped（162.63 秒）**，Ruff 通过；六对提示、冻结哈希与密钥泄漏检查通过。未重跑 Linux、Docker、HTTP，默认服务与冻结引擎未修改。

首轮适配器直接修改不可变配置，产生 `FrozenInstanceError`；全部在模型请求前失败，模型调用为 0。该未完成记录保留在 `.tmp/real-defects/provider-compare-v1-live`，不计入上述结果。修复并新增入口测试后，完整重新运行到 `.tmp/real-defects/provider-compare-v1-final`。

机器摘要：[provider-compare-v1.json](provider-compare-v1.json)。真实复跑需要既有六项准入快照、独立检查、隔离 Python、公开检查认证、原 Qwen 模型和 DeepSeek 密钥；仅克隆仓库不足以重建历史输入。单元测试不需要真实 API Key。

```powershell
$env:TEMP='D:\project_other\CoreCoder\.tmp\python-temp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
python -B -m pytest tests/test_provider_compare.py -q -p no:cacheprovider --basetemp .tmp/pytest-provider-rerun
python -B -m docs.experiments.provider_compare_v1 --output .tmp/real-defects/provider-compare-rerun
```

每次使用全新输出目录。所有新增实验产物继续放 D 盘。
