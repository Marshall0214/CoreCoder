# contract-check-v1：契约与修复覆盖检查

更新：2026-10-04。该阶段是**独立 Prompt 干预**，不是检索或去重策略收益。新增 `--prompt-policy baseline|contract-check`，默认 baseline。是否改善修复仍需真实运行验证。

## 干预定义

baseline 保持原提示逐字不变。contract-check 在用户提示后追加通用检查要求：维护一次紧凑的症状/契约清单，为每项关联实现路径、期望行为和验证状态；不要只修第一处可疑实现；读到足够证据后实施修复，不反复改写计划；结束前检查所有项及跨模块交互、执行许可的可见测试，并简述已修与未确认行为。没有追加 LLM 调用或固定反思轮数，没有新工具或修改独立评分。

清单由模型从原缺陷描述和仓库文档形成。提示构造函数只接收缺陷描述、允许源码列表、搜索设置及提示策略，不读取参考补丁、相关文件标签或目标测试。要求不含任务特定答案。它不是结构化状态机，也不强制模型输出合法 JSON 或实际遵守清单；预算终止时可能没有最终覆盖说明。

检查完整性与减少重复计划是本版本提示的两个要求，作为一个整体报告；本轮不能分离二者的贡献。新增提示本身增加输入开销，效果可能为零或负面。缺失最终说明不能直接证明模型没有检查，最终说明也不能替代父进程独立验收。

## 预先固定的 Pilot

选择已有 pagination-cursor 和 lease-lifecycle，分别执行一次 baseline 和 contract-check，共四次。分页先 baseline 后检查，租约反序。仅 prompt_policy 不同；关键词、search-history=full、context-policy=none、预算 30,000、输出 2,048、轮数 12、上下文估算 16,000、Worker 180 秒、测试 15 秒、正文字符 6,000 固定。Ollama qwen3.5:27b、temperature=0、reasoning_effort=none。

两组在共同代码版本、干净工作区重新执行，不将旧版本结果替代控制。工具/任务/评分哈希应一致，规范化 Prompt 哈希应不同。全部失败保留，不选择性重跑。先检查修复覆盖、首次修改前消耗、计划调用数及独立验收，再决定是否追加预先固定的重复运行；四次 pilot 不用于稳定成功率或显著性结论。

## 复跑

```powershell
python -m pytest tests/test_prompt_policy.py -q
python -m pytest tests -q
foreach ($policy in @('baseline', 'contract-check')) {
    python -m evals --suite evals/fixtures/localization-v1 --task pagination-cursor --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --search-history full --context-policy none --prompt-policy $policy --output ".tmp/evals/contract-check-v1/pilot/pagination-cursor/$policy"
}
foreach ($policy in @('contract-check', 'baseline')) {
    python -m evals --suite evals/fixtures/retrieval-overlap-v1 --task lease-lifecycle --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --search-history full --context-policy none --prompt-policy $policy --output ".tmp/evals/contract-check-v1/pilot/lease-lifecycle/$policy"
}
python -m evals.diagnostics .tmp/evals/contract-check-v1/pilot --output .tmp/evals/contract-check-v1/pilot-phase-diagnostics.json
```

新实验请使用新目录。返回码 1 表示未全部通过，不等于基础设施故障；核实报告完整性。原始目录被 Git 忽略，需要独立备份。

## 已执行结果

| 任务/策略 | 状态 | 总实际 Token | LLM 调用 | 计划 / 搜索 / 读取 / 编辑 | 修改文件 |
| --- | --- | --- | --- | --- | --- |
| pagination / baseline | budget_exceeded | 25,565 | 7 | 3 / 2 / 5 / 0 | 无 |
| pagination / contract-check | budget_exceeded | 27,620 | 8 | 2 / 1 / 4 / 1 | query.py |
| lease / contract-check | budget_exceeded | 24,366 | 6 | 1 / 1 / 4 / 0 | 无 |
| lease / baseline | budget_exceeded | 25,869 | 6 | 2 / 1 / 14 / 0 | 无 |

两组主验收和候选独立验收均 **0/2**。四次可见回归通过，均未调用可见测试工具；目标测试失败。无基础设施故障或 usage 缺失。所有终止均为累计预算预检，未触及轮数或上下文窗口上限。四次 pilot 不扩大为完整重复实验。

分页检查组直到第八次请求后才尝试编辑，此前累计 27,620 Token；修复 query.py 后剩余 2,380，下一次预留需要 7,382，因此未修续页游标或运行测试。其他三次没有编辑尝试，各自整个运行均属于编辑前消耗。

检查组的计划调用更少，租约读取也少，但仍无法完成全部修复。检查组租约计划列出三个症状，尚未建立契约、实际实现路径和验证状态的对应关系；分页计划仍是通用的搜索、读取、定位、修复步骤。预算终止没有最终覆盖说明，不能据此推断模型内部是否做过检查；**目前没有证据证明通用提示带来了可靠的契约覆盖行为**。不能将计划调用减少称为任务成功提升。

追加提示使首轮 user 消息估算从分页 221 增至 468、租约 251 增至 498，约增加 247；该文本随后续请求重复携带。估算不是实际计费。计划开销、读取数量和轨迹同时变化，不能凭两组单次运行归因各子要求的作用。

## 验证、版本与产物

新增 5 项测试检查默认提示逐字保持、非法策略拒绝、真实 Worker 的工具/评分一致及提示差异。全量 **276 passed、1 skipped，46.93 秒**；Ruff 通过，Windows 符号链接测试跳过。

四次源码哈希一致：`e2bba6bdf9878e6f36daf721b4de360e7bfb3994fad7cb2e5c3e0b3499057ca1`。同任务两组的 fixture、grader、manifest、工具 Schema 相同，规范化 Prompt 不同；配置仅 prompt_policy 不同。baseline 文本与旧版本一致，但本轮控制是共同代码版本的新运行。

- [pagination baseline](../.tmp/evals/contract-check-v1/pilot/pagination-cursor/baseline/summary-819b32e0be.md)
- [pagination contract-check](../.tmp/evals/contract-check-v1/pilot/pagination-cursor/contract-check/summary-7f7865c8f3.md)
- [lease contract-check](../.tmp/evals/contract-check-v1/pilot/lease-lifecycle/contract-check/summary-39a69a3b39.md)
- [lease baseline](../.tmp/evals/contract-check-v1/pilot/lease-lifecycle/baseline/summary-af6829ccf2.md)

同名 JSON 保存完整报告，阶段诊断见 `.tmp/evals/contract-check-v1/pilot-phase-diagnostics.json`。原始 Trace 中保留工具计划、编辑和预检事件；不包含内部推理。目录需独立备份。

## 下一步决定

baseline 仍为默认，contract-check 作为可选 Prompt 实验保留，不继续堆叠提示或重复本轮。先做**固定公开证据的补丁能力诊断**：仅把缺陷描述、允许源码和模型可读的仓库契约一次性提供给模型，请其输出范围受限的补丁，再由原独立验证器验收。不提供相关文件标签、参考答案或目标测试。

该模式改变信息提供与执行协议，只用于区分“证据已齐备时仍生成不完整补丁”与“工具循环/上下文获取开销阻碍修复”，不能与 Agent 成功率当作公平效果对比，也不能称为 RAG 提升。它尚未实现。根据诊断结果，再决定优先处理模型/结构化修复，还是执行与上下文机制；主任务、原预算和所有失败继续保留。
