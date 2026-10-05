# 真实开发任务统一入口 v1

## 本次做了什么

新增 `python -m evals.real_suite`，按 `evals/real_defects/development-suite-v1.json` 的固定顺序执行三个任务目录中的全部 7 个任务。复用现有修复、预算和父评测器，不改变 Agent 策略。

清单冻结目录 SHA-256、任务顺序、RunConfig 全部字段和默认 3 轮重复。固定 qwen3.5:27b、Ollama `/v1`、temperature=0、reasoning_effort=none；每任务 12 轮、30,000 Token 预算、2,048 输出 Token、16,000 上下文 Token、180 秒 Worker 超时、15 秒测试超时。检索 off，默认 agent-loop。Token 预算含估算预检查，不是服务商账单硬上限。

任务包括 help-eagerness、flag-default-map、resource-exception、flag-envvar、prompt-suffix、invoke-missing、shared-default。6 个参考单文件修复、1 个参考跨文件修复，全部为 Click 开发任务。

批量运行前检查全部目录哈希、准入检查及源码快照哈希，并要求准入记录的测试环境完全相同。早期三任务已在既有无第三方依赖解释器中重新准入，记录位于 `.tmp/real-defects/mixed-original-admission-v1/admission.json`；其余复用 crossfile-admission-v2 和 expansion-admission-v1。

所有模式均独立创建工作目录；原始版本、参考修复、脚本检查分别用于复现失败、验证评分和验证 Worker 链路。live 只获得公开描述与 Controls，Target 和参考补丁不进入模型任务。特殊 symbol-feedback/base/linked 协议不属于本轮基线。

## 结果与中断

新输出目录中保存 `suite-report.json`、汇总报告、每个任务的 Trace、补丁和独立评分日志。suite-report 保存完整清单、实际配置、准入文件哈希、源码实现哈希、重复编号、预期次数与已完成次数；每个任务完成即更新。

失败保留在分母；取消时停止并标记 complete=false，不能把已完成部分当完整矩阵。complete 表示全部运行完成，不表示全部修复通过。unchanged 全部 failed_verification 时 CLI 返回 0；其他模式要求全部 passed，否则返回 1，live 修复失败不会提前结束其余任务。

## 复现

在仓库根目录、corecoder 环境执行，output 使用新路径：

```powershell
python -m evals.real_suite --mode unchanged --repeat 1 --admission original=.tmp/real-defects/mixed-original-admission-v1/admission.json --admission crossfile=.tmp/real-defects/crossfile-admission-v2/admission.json --admission expansion=.tmp/real-defects/expansion-admission-v1/admission.json --output .tmp/real-defects/mixed-suite-unchanged-replay
```

将 mode 分别换为 reference、scripted，使用不同 output。一次真实模型试运行使用 `--mode live --repeat 1`；冻结清单默认三轮基线使用 `--mode live`，去掉 repeat 覆盖，并使用新 output。

跨机器需要重新准入三个目录，显式传入同一个测试解释器，再将三个 admission 路径传给批量入口。清单不绑定本机 `.tmp` 路径。模型名称不锁定服务端内容；更换模型权重或 Ollama 设置时必须另记环境，不能混为同一实验。

## 验证与证据

离线验收各 7 次：unchanged 全部 failed_verification；reference、scripted 全部 passed，共 21 次预期结果一致。

证据目录：`.tmp/real-defects/mixed-suite-{unchanged,reference,scripted}-v1`。原始 Target 失败、Controls 通过，参考和脚本目标/控制检查通过；这些检查不是完整上游测试套件。

代码验证：相关测试 31 passed；全量 567 passed、1 skipped；新增模块和测试通过 Ruff。测试覆盖目录漂移、任务顺序变化、不完整配置、错误分组、环境不一致、失败保留及取消后的不完整矩阵。

真实模型单轮试运行结果另记在下方；默认三轮基线尚未执行。开发案例与策略之间有已知接触，所有结果 benchmark_eligible=false，不能用于宣称留出性能或优于成熟产品。

## 真实模型单轮试运行

证据：`.tmp/real-defects/mixed-suite-live-pilot-v1/suite-report.json`，7/7 次运行完成，修复通过 0/7。所有任务均为 budget_exceeded，未产生源码修改；原始 Target 仍失败，Controls 仍通过。不把这轮单次通过比例当作稳定成功率。

| 任务 | 已知输入+输出 Token | 单任务总秒数 |
| --- | --- | --- |
| help-eagerness | 26,419 | 24.1141 |
| flag-default-map | 24,671 | 17.8884 |
| resource-exception | 24,207 | 22.2659 |
| flag-envvar | 26,932 | 17.6876 |
| prompt-suffix | 28,045 | 17.2241 |
| invoke-missing | 27,216 | 16.1656 |
| shared-default | 25,319 | 22.2480 |

已知 Token 合计 182,809，无 missing_usage_calls；单任务总时间合计 137.5937 秒，包含工作区及评分等开销，不是纯模型延迟。所有任务实现哈希一致：`76dd89c52a9062c995711a8f825c83b1f0e33f2e3247faa4d5e9e7c0e330ae54`。

模型服务检查时 qwen3.5:27b 的 Ollama digest 为 `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`。批量入口目前不自动锁定权重 digest 或服务端推理设置，这项记录是环境观察，复跑仍需核对。

七次 Trace 均记录 budget_blocked.reason=cumulative_preflight：下一次请求的估算输入和输出预留大于剩余累计预算，因此在实际已知用量达到 30,000 前停止。不是服务错误、超时或最终断言修复失败。每任务 read_file 3–7 次；help 案例包含连续读取 core.py 的多个 500 行片段。结果表明在这些运行中，工具观察/历史累计成本挤占了修复预算；不能据此断言模型本身没有修复能力，也尚未证明检索策略能够改善结果。

CLI 返回 1 表示本轮没有全部修复通过，完整矩阵仍已保存。下一步先完成同配置三轮默认基线，再定义只改变检索与上下文策略的成对对照，保留全部预算失败。
