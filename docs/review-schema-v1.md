# 审查结构化输出约束

## 目的与协议

上一阶段金额审查出现不完整 JSON，导致有效测试未进入反馈。本阶段新增 `--public-check-policy contract-schema`，协议为 `public-contract-feedback-v4-schema`；generated、reviewed 和 contract-only 均保留，默认不变。

仅审查调用发送 `response_format=json_schema`，根据当前公开输入构建约束：

- 必须输出 reviews；条目数量等于生成测试数，字段必填，禁止额外字段。
- 测试名、契约 ID、verdict 与 reason_code 使用枚举，不能自由生成不存在的名称。
- 数值断言序号来自实际测试，限制推导数量、表达式长度和字符集；表达式禁止等号及长篇解释，仅保留纯算术表达式。
- 调用后恢复模型参数，测试生成、初次修复和反馈修复不继承该 Schema。

Ollama 官方文档说明其 OpenAI 兼容接口支持 response_format：[Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)。实现记录实际 Schema 到 `public-check-review-format.json`，保存 `review_schema_hash`；Schema 的序列化估算开销纳入累计 Token 和上下文预检，实际用量继续以服务端返回值记录。

不自动补全或修复 JSON，不增加格式重试机会，不静默去掉约束参数。提供方不支持时记录调用失败；支持也不保证输出不会因 Token/时间上限截断。新增 `provider_finish_reason` Trace，帮助区分正常结束与长度终止。

## 本地验证边界

Schema 不证明引用支持期望值，不保证没有重复测试、推导公式正确或行为覆盖充分。保留原来的逐项完整性、契约 ID 解析、纯表达式范围、AST/Decimal 运算与原期望比较；即使提供方忽略约束，本地检查仍能拒绝不合规审查。

不成立的数学推导不会因为 JSON 合法而获准反馈。格式失败关闭审查并继续初次补丁流程，原始输出保留；隐藏目标与原有回归仍由父进程独立执行。预算保持不变，最多四次调用，不把格式通过率当作修复成功率。

## 验证与复跑

```powershell
python -m pytest tests/test_review_schema.py tests/test_contract_catalog.py tests/test_check_review.py tests/test_check_arithmetic.py tests/test_contract_feedback.py -q
python -m pytest tests -q
python -m evals --suite evals/fixtures/localization-v1 --mode contract-feedback --task checkout-rounding --task pagination-cursor --public-check-policy contract-schema --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --evidence-order path --patch-policy contract-coverage --output .tmp/evals/review-schema-v1-replay
```

查看 `worker-result.json` 的 review_status、accepted_tests、numeric_error、feedback_attempts，及 Trace 中 response_format_estimate、provider_finish_reason。最终结论看独立 accepted/verification。保存 Schema、原始响应及冻结检查；`.tmp/` 被 Git 忽略，应独立备份。

## 2026-10-05 共同版本试点

73 项相关测试通过；全量 **408 passed、1 skipped**；改动运行时和测试文件 Ruff 检查通过。两个预先固定任务各一次，模型 Ollama `qwen3.5:27b`，temperature 0、reasoning none、单次输出 2048 Token、累计 30000 Token、上下文估计 16000、worker 180 秒、测试 15 秒，keyword K=5、深度 2、6000 字符、path 顺序、contract-coverage 修复策略。

| 任务 | 审查有效 | 生成/保留检查 | 反馈次数 | 最终公开检查 | 独立验收 | 调用数 | 总 Token | 总耗时 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| checkout-rounding | 是 | 6/4 | 0 | 通过 | 通过 | 3 | 5980 | 49.95 秒 |
| pagination-cursor | 是 | 6/5 | 1 | 通过 | 通过 | 4 | 9816 | 64.67 秒 |

金额两个错误折扣期望仍被本地算术校验拒绝，避免用格式合法性掩盖错误期望；其余四项在原始代码上失败、初次修复后通过，未触发多余反馈。分页保留五项，异常 limit 检查因公开契约不足不参与反馈；原始/初次补丁检查失败，一次反馈后检查及独立验收通过。

Schema 只进入第二次审查调用，预检分别增加估算 476/472 Token，其他调用没有 response_format 开销；实际用量完整，七次调用 finish_reason 均为 stop，无格式重试、截断或预算终止。总计 2/2 独立通过、7 次调用、15796 Token。审查输入仍是契约目录、接口与生成测试，隐藏测试/参考补丁未参与。

报告 `.tmp/evals/review-schema-v1-pilot/summary-cfd3fd202d.json`，共同源码哈希 `73686fb38d420e0965a45c7c8ad0dad01cddabc1957d5c9b9513d70ef59dbdf3`。旧失败未重写；不同协议不合并成绩。

当前仅两项、每项一次，不能声称格式失败已彻底消除或修复成功率稳定提升。与上一阶段相比还改变了表达式格式提示和解码约束，不将结果单独归因于检索或某个提示句。下一步冻结共同版本，扩展到完整 localization-v1 多轮对照，保留失败与全部开销；默认策略继续不变。
