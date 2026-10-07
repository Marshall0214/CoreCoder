# 公开执行参数轨迹：结果与停止结论

本轮实现实际参数/执行行反馈，并完成零推理审计和真实配对。两组独立验收均 **1/2**，Controls 均 **1/2**；none-salt 未修复，不采用、不扩大本策略，不修改默认 Agent 或服务。配置、评分、轨迹、预算和冻结来源见 [机器摘要](parameter-trace-v1.json)。

## 新信息是什么

此前关系矩阵描述“应该如何传递”；本轮 [采集器](experiments/parameter_trace_v1.py) 记录公开检查执行候选时“实际传了什么”。通过隔离 Python 的 `sys.settrace`，只匹配刷新证据中的函数路径、函数名及范围，记录进入函数、指定值变化前的执行行和函数退出；不改源码，不读取参考修复或私有评分。

仅记录 `salt`、`args`、`prefix`、`prog`、`text_width` 和实例字典中的 `salt`、`width`、`current_indent`。基本类型直接编码，字符串与 bytes 限长，其他对象只标记未记录，不调用 `repr`；不记录密钥、完整 locals、签名或载荷。该白名单为这批公开任务设计，尚不是通用任意仓库观测工具。行事件发生在语句执行之前，不能直接将到达某行解释为分支条件真假。退出事件未记录返回值，不能据此声称输出追踪。

仅运行已认证公开检查，校验源码及检查不变。两组均采集，将完整观测中的测试结果、失败和 traceback 与普通公开检查对比；不一致、超时或基础设施失败会停止分支。代码对象缓存避免对每个标准库行重复解析文件路径；早期离线实现曾触发超时，修正后才进行正式模型实验。

## 固定预算下的离线审计

[审计入口](experiments/parameter_trace_audit_v1.py) 在上轮历史第一候选上执行公开检查：零模型请求、零私有评分。Click 26 个事件，none-salt 采集上限 400 个，均与普通公开结果一致。达到上限后丢弃后续事件，选取失败测试的事件按执行顺序装填；这不是全部测试或全部调用路径覆盖。

源码与序列化轨迹共享原 **6,000 字符**预算，轨迹另限最多 1,700 字符；不移除现有源码片段为轨迹腾空间。Click 只剩 324 字符，装不下有效事件，Worker 不向模型加入空轨迹。none-salt 可容纳六个事件，显示实际 `None` 从 `Serializer.__init__` 进入 `make_signer` 和 `Signer.__init__`。完整轨迹留在本地诊断工件，不全部发给模型。

## 真实配对

[Worker](experiments/parameter_trace_worker_v1.py) 维持在当前候选上修复，不使用上一轮源码重启。第一轮提示成对一致；第二轮模型、片段替换协议、严格 JSON 封装处理、公开测试和评分保持一致，仅候选组可添加预算内的真实事件。最多两次调用，共享 15,000 Token，关闭思考，Qwen `qwen3.5:27b`。

| 任务 | 普通反馈 | 参数轨迹反馈 | 是否实际加入轨迹 |
| --- | --- | --- | --- |
| click-usage-empty | 通过 | 通过 | 否；仅作回归对照 |
| itsdangerous-none-salt | 目标及 Controls 失败 | 目标及 Controls 失败 | 是；六个事件 |

候选 none-salt 反馈源码与轨迹合计 **5,896 字符**。没有预算停止或结构拒绝。模型看到传递的 `None` 后仍给两个构造函数加固定默认盐值，没有恢复首轮删除的方法级回退。none-salt 两组最终 Python AST 相同（Click 最终 AST 不同，但两组均通过），增加观测未改变本轮修复逻辑。

八次新本地请求共 **34,252 Token**：基线 16,903，候选 17,349。两项各一次、已查看任务；有效干预只有 none-salt 一项。不能用两项结果声称通用轨迹策略无效，更不能把 Click 的通过归功于未加入的轨迹。Worker 合计约 65.43 / 71.61 秒，仅是本次成本记录。

## 验收和下一步

新增 **5 项测试通过**，验证真实隔离检查、普通/追踪观测一致、失败事件筛选、字符上限、基本值编码及不调用任意对象 repr。Windows 全量 **1,181 passed、2 skipped，202.23 秒**；Ruff 通过，冻结输入和模型身份校验通过。零 DeepSeek 请求；临时数据在 D 盘，未重跑 Linux/容器/HTTP 验收。

本策略到此停止，不再围绕该单例增加提示字段。当前证据支持的结论是：已提供完整源码、公开检查、语义关系、历史差异及部分实际执行值，仍未改善 none-salt。后续核心实验应先梳理失败类型与任务覆盖，留出未用于开发的新缺陷，明确是否要改变推理/探索流程或模型配置，再做一个有停止条件的实验；不将更多诊断字段、测试数量或报告数量当成修复收益。

复现需要历史认证源码、评分环境和审计工件，输出目录须全新。正式对照固定读取 `.tmp/real-defects/parameter-trace-audit-v1-certified/audit.json`：

```powershell
python -m pytest tests/test_parameter_trace.py -q -p no:cacheprovider --basetemp .tmp/parameter-trace-tests-user
python -m docs.experiments.parameter_trace_audit_v1 --output .tmp/real-defects/parameter-trace-audit-user
python -m docs.experiments.parameter_trace_compare_v1 --output .tmp/real-defects/parameter-trace-compare-user
```

原始对照记录为 `.tmp/real-defects/parameter-trace-compare-v1/experiment.json`，完整观察位于各分支 `parameter-observation/observation.json`。这些运行工件不随 Git 发布；审计到新目录不会自动替换固定认证输入。
