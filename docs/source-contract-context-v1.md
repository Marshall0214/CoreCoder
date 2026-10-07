# 源码契约上下文对照 v1

## 问题与离线审查

上一轮 Qwen / DeepSeek 都未修好 `itsdangerous-none-salt`。本轮固定本地 Qwen，检查补充源码契约证据能否改善结果，不调用 DeepSeek。

零模型调用的离线审查发现：原初始上下文已经包含 `Signer.__init__` 和 `Serializer.__init__` 的两个不同默认盐值，因此不能说模型不知道默认值。原五个片段还包括 JWS 构造函数、unsign、dumps，但缺少 make_signer、iter_unsigners 与 loads 的完整参数传递关系，也未展示类范围的相关赋值清单。

此前已比较过反馈时增加转发函数、人工关系矩阵；本轮新增的是**从当前源码自动提取的带来源事实**，同时在同一预算内重新组织片段。不是再次把人工矩阵换一个名字，也不能单独把结果归因于事实摘要或片段排序中的某一项。

## 做了什么

- [事实提取与打包](experiments/source_contract_context_v1.py)：解析公开描述中点名的类与参数，从允许源码提取默认值、相关赋值、条件与调用表达式，记录路径、行号和文件 SHA256。只报告源码现状，不提供修复代码或从隐藏评分推导规则。
- 初始候选保留 Serializer/Signer 构造函数、make_signer 和 iter_unsigners 四个完整片段，附带 dumps、loads 等方法的参数传递事实。事实序列化长度 1,684，片段正文 3,945，合计 **5,629 字符**；两组上限均为 6,000，最多五个完整函数片段，事实另限 2,000 字符，记录丢弃项，不截断半个函数。
- [修复 Worker](experiments/source_contract_worker_v1.py)：生成提示与调用编辑器使用同一份经过版本验证的片段；公开或事务反馈后基于当前候选重新提取事实。run_candidate、pack_feedback、transaction_feedback 与冻结统一流程的 AST 一致，由回归测试核查。
- [对照入口](experiments/source_contract_compare_v1.py)：先要求当前提取器的零调用审查记录，再重新运行六项任务，每项两组各一次；只有 none-salt 改变上下文，其他五项提示保持相同，作为回归检查。

赋值清单是 AST 语法扫描的启发式结果，未实现严格作用域、继承、动态属性或别名解析，不能证明成员不存在或运行行为正确。函数事实带方法和语句位置；编辑仍锚定完整源码片段的唯一匹配，不使用事实摘要作为编辑原文。

Qwen 模型摘要、非流式适配器、temperature=0、top_p=1、reasoning_effort=none、输出 2,048、执行器上下文预检查 16,000、预算 15,000、最多两次请求、事务校验、公开检查版本和独立评分均保持一致。执行器上下文限制不代表重新设置了 Ollama 原生窗口。工具集合为空，SDK 自动重试为零，原任务和评分不变，未接入默认服务。

## 结果

| 任务 | 原上下文 | 源码契约上下文 |
| --- | --- | --- |
| click-usage-empty | 通过 | 通过 |
| click-echo-empty-bytes | 通过 | 通过 |
| click-style-color-validation | 通过 | 通过 |
| itsdangerous-none-salt | Target 失败，Controls 通过 | Target 与 Controls 都失败 |
| itsdangerous-future-age | 通过 | 通过 |
| itsdangerous-malformed-time | 通过 | 通过 |

| 指标 | 原上下文 | 源码契约上下文 |
| --- | --- | --- |
| 独立验收 | 5/6 | 5/6 |
| 模型请求 | 8 | 7 |
| Prompt Token | 21,579 | 17,068 |
| Completion Token | 3,834 | 3,325 |
| 总 Token | 25,413 | 20,393 |
| Worker 总耗时 | 114.17 秒 | 104.81 秒 |
| 事务拒绝 | 0 | 0 |

共 **15 次本地 Qwen 请求、45,806 Token、0 次 DeepSeek 请求**。所有回答正常结束，无截断、预算停止或返回思考字段。五对回归初始提示相同，none-salt 的初始提示按预期不同；冻结文件、来源与评分哈希检查通过。

候选在 none-salt 只修改了 make_signer 和 iter_unsigners，删除原有 `salt is None → self.salt` 分支，却没有修复两个构造函数对 None 的处理。补丁可以编译并加载模块，但签名时产生 TypeError，原默认与实例盐值行为也回归，Controls 失败。

候选公开检查结果为 `FAILED (failures=12, errors=8)`，同时存在断言失败与执行错误。既有统一流程只对有效断言失败且无执行错误的配对检查进行反馈，因此候选停止于第一轮，原上下文使用了第二轮反馈。**Token 减少源于少一次调用及失败提前停止，不能宣称实现了效率优化。** 本轮不改变这个反馈门槛来追求成功数。

这是六项已查看任务各一次的探索性实验，没有未见任务泛化证据；通过仅表示满足独立 Target/Controls 与修改约束。耗时是本轮观测，不作为稳定性能比例。首次候选没有触发第二轮，因此候选反馈时重新提取的工程行为由单元测试验证，不宣称本轮真实模型验证过该路径。

**结论：补充这些源码事实未提升成功率，且 none-salt 出现行为回归。冻结可选原型，不替换默认策略，不扩大重试。** 至此已有模型、转发上下文、人工关系矩阵与源码事实的失败证据；建议收敛项目交付，将契约推理与公开执行错误反馈列为后续问题，避免围绕同一已查看任务持续调参。

## 验收与复跑

提取器新增 10 项测试；与供应商适配器、统一流程一起 **40 passed**。最终 Windows 全量 **1,023 passed、2 skipped（174.23 秒）**，Ruff 通过。未重跑 Linux、Docker、HTTP；原冻结模块与默认服务未修改。机器摘要：[source-contract-context-v1.json](source-contract-context-v1.json)。

离线审查记录在 `.tmp/real-defects/source-contract-audit-v1/audit.json`，完整真实对照在 `.tmp/real-defects/source-contract-compare-v1/experiment.json`，原始产物不进入 Git。模型复跑需要原六项准入快照、隔离 Python、评分与公开认证、冻结 Qwen；不需要 DeepSeek Key。

```powershell
$env:TEMP='D:\project_other\CoreCoder\.tmp\python-temp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
python -B -m pytest tests/test_source_contract_context.py tests/test_provider_compare.py tests/test_unified_feedback.py -q -p no:cacheprovider --basetemp .tmp/pytest-source-contract-rerun
python -B -m docs.experiments.source_contract_compare_v1 --audit-only --output .tmp/real-defects/source-contract-audit-rerun
python -B -m docs.experiments.source_contract_compare_v1 --output .tmp/real-defects/source-contract-compare-rerun
```

真实对照读取固定的 `source-contract-audit-v1/audit.json` 认证；第二条生成新的审查副本用于核对，不覆盖旧记录。提取器变更需另建协议版本与认证入口。所有新增产物放 D 盘，每次输出使用新目录。
