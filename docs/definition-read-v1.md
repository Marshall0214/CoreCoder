# 定义边界读取原型 v1

## 本轮实现

独立模块 `docs/experiments/definition_read_v1.py` 提供标准 Tool 接口的 `read_definition`，可导出 Function Calling schema，尚未注册到默认 Agent 或现有定位 Worker。原 read_file、修复实现、检查点和冻结协议保持不变。

输入为允许源码的相对路径、精确限定符号名和可选继续偏移。例如 `Context.invoke`、`outer.inner`；通过 AST 解析定义，不写死任务行号。

返回 JSON 包含文件 SHA、`definition_range`、`shown_range`、`complete_symbol`、`missing_ranges`、`next_offset`、限制原因及带原始行号的内容。单次最多 **120 行、6,000 个完整 JSON 字符**，包括元数据与转义开销；不删除文档或制造源码子串。

## 边界与正确性

- 定义范围包括装饰器，支持类、普通函数、异步函数和限定的嵌套函数。
- 对明确导入的 typing / typing_extensions overload 声明，选择唯一非 overload 实现，并报告声明数。重复实现、只有声明、缺失符号或语法错误直接报错；不按最长定义猜测。动态绑定与复杂导入别名不作执行解析。
- 只从定义内读取。超限后返回真实已显示范围和继续偏移，不拆开单行、不伪造被截断文本。单行本身超过响应预算时标记 blocked，保持继续偏移不变，不跳过该行。
- `complete_symbol` 只描述本次响应是否覆盖整个定义。最后一页虽然 `next_offset=null`，但仍标记此前范围缺失；后续工作流须自行汇总多页证据，不能把尾页当成完整定义。
- 拒绝允许列表外文件、目录逃逸、路径符号链接和定义外偏移。读取前后确认文件字节一致，只有成功返回的原文行生成带版本的 receipt；可直接交给现有 read_fragments 校验转换。
- 该原型不扩展写权限，不执行源码，不调用模型。工具参数不是跨任务状态，源码变化后旧 receipt 不再有效。

## 真实源码离线验证

使用原 prompt-suffix before 源码，调用 `read_definition(file_path="src/click/termui.py", symbol="prompt")`：

| 指标 | 结果 |
| --- | --- |
| 定义范围 / 展示范围 | 83–191 / 83–191 |
| 返回源码行 | 109 |
| complete_symbol | true |
| missing_ranges | 空 |
| next_offset | null |
| 编号正文字符 | 4,706 |
| 完整响应 JSON 字符 | 5,286 |

保留了文档、转换和确认流程，并补足原读取缺失的 183–191 行。满足原行数与字符上限，但没有将结果插入旧检查点，没有运行修复模型，也不宣称成功率或 Token 收益。完整定义进入候选池后仍可能受 6,000 字符装填预算影响。

## 下一步

先冻结独立定位试验协议，再将原型接入可选 Worker，保持源码范围、模型、阶段预算及独立评分不变，记录调用轨迹、完整性、重复读取和候选池变化。新增工具会改变 schema 与模型可用接口，应作为定位工作流干预报告，不能混同此前“仅改变装填”的配对实验。

优先做小规模 pilot，核对 Agent 是否使用完整性信息、是否减少重复读取，以及工具返回 JSON 的历史开销。若改变工具调用后仍未改善缺陷验收，应保留负面结果；不扩大预算、不用隐藏测试或参考补丁指导符号选择。

## 复现与测试

```powershell
python docs/experiments/definition_read_v1.py --workspace .tmp/real-defects/expansion-admission-v1/click-prompt-suffix/before --allow src/click/termui.py --file src/click/termui.py --symbol prompt --output .tmp/real-defects/definition-read-v1-rerun
python -m pytest tests/test_definition_read.py tests/test_staged_acquisition_audit.py tests/test_staged_containment_packing.py tests/test_staged_failure_audit.py tests/test_staged_compact_live.py tests/test_staged_compact_packing.py tests/test_staged_evidence_coverage.py tests/test_staged_replay.py tests/test_staged_repair.py -q
```

输出必须是源码目录外的新目录。本轮产物 `.tmp/real-defects/definition-read-v1/` 包含 `response.json`、`receipts.json` 和带脚本 SHA 的 `provenance.json`，被 Git 忽略。

17 项新增测试及相关回归共 **71 passed**，Ruff 通过。覆盖装饰器及文档、分页完整性、完整 JSON 字符上限、超长单行、嵌套/异步/重载、歧义和语法错误、范围与类型约束、CRLF/Unicode 和读取时源码漂移。未重跑全量测试。

后续独立定位 pilot 已执行，结果及限制见 [definition-localization-v1.md](definition-localization-v1.md)。
