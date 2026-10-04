# patch-coverage-v1：单请求契约覆盖生成对照

日期：2026-10-04。新增 `--patch-policy baseline|contract-coverage`，仅适用于 pipeline，默认 baseline 保留原系统提示和请求正文。与 Agent 的 prompt-policy=contract-check 分开；本项是生成提示、输出结构及校验的联合干预，不是检索收益实验。

## 机制与边界

contract-coverage 在同一次请求中先输出 coverage，再输出 edits。每项 coverage 包含 behavior、evidence_file、evidence_quote、code_files、action（edit/preserve）；要求从公开描述和已提供契约列出适用约束及保持行为，并关联已提供源码。没有任务专用答案、参考修复或隐藏测试输入。

运行时检查严格字段、1至16项清单、非空/限长文字、引用为描述或已提供文件的精确非空子串、code_files为已提供且允许修改的源码；引用可来自 description 或文档。清单校验错误记录为 coverage_status=invalid、coverage_error，不阻断合法补丁；错误清单不作为有效 coverage_claims 发布，原回答仍完整保留。顶层必须恰好为 coverage/edits，补丁继续使用原有严格校验、版本与修改范围限制、全体编辑先暂存再写入和CRLF字节保留。没有自动格式修复、额外模型调用或失败后隐藏测试反馈。

这些校验只验证引用存在与结构有效，**不证明引用支持行为、不证明清单穷尽、不证明 action正确或代码已修复**。pipeline_coverage_validated/rejected 明确记录 semantic_coverage_verified=false；模型自报完成不能改变父进程验收。覆盖策略增加输出和约束，也可能增加顶层/补丁格式失败与Token，按失败计入结果；清单诊断错误与修复验收结果分别报告。

## 小样本冻结协议

完整 localization-v1 五项各跑 baseline/contract-coverage 一次，共十次，从干净工作区开始。按任务交错顺序：归档 baseline→coverage、金额 coverage→baseline、事件 baseline→coverage、截止时间 coverage→baseline、分页 baseline→coverage。预先包含全部五项，不根据中途结果筛选或调参；历史15次基线不并入本轮。

Qwen3.5:27b Q4_K_M、temperature=0、reasoning_effort=none、keyword、K5、依赖深度2、selection顺序、正文6,000字符、Token30,000、输出2,048、估算上下文16,000、Worker180秒、测试15秒、每次一次逻辑模型调用。固定原父进程目标/回归评分。两组只改变patch_policy；提示和输出结构是该变量的一部分，不将相同预算解释为相同实际Token。

先验目的为验证输出结构、预算与遗漏行为是否有改善迹象，单次/任务不支持稳定成功率、统计显著性或泛化；有有效迹象后再做共同版本的重复对照。

## 初版失败与修正

第一批采用阻断式清单校验：baseline 1/5，覆盖组0/5，其中三项因关联未提供的旁支源码被拒绝，一项因引用不是精确子串被拒绝；分页清单有效但实际修复仍不完整。第一批源码哈希 `585036d65a8df939d3dd570d1449986e15ef3ac704bcef50e6135b1ace16a41d`，完整结果 `.tmp/evals/patch-coverage-v1/summary-03cf8fa791.json`、`comparison-audit.json`，全部失败保留。

事后仅提取原模型 edits，在新工作区通过原补丁校验及父进程独立验证，4/5通过，分页仍失败。该诊断未调用新模型，记录在 `.tmp/evals/patch-coverage-v1/patch-only-replay/summary.json`；benchmark_eligible=false，不替换第一批失败计分，不作为最终策略成绩。

初版错误是让辅助诊断元数据否决合法补丁。最终版分开清单诊断和补丁校验，生成提示未更改；清单错误保留但不阻断修复，补丁格式、提供过的源码、版本与范围检查始终严格。完整测试330 passed、1 skipped（Windows符号链接环境），Ruff通过；包含错误清单不丢弃合法补丁、不绕过越界校验、模型自报不能覆盖独立验收、CRLF保留、baseline提示哈希不变等验证。

修正后在 `.tmp/evals/patch-coverage-v1-advisory` 新批次重新执行全部十次，两组共享最终源码，旧版本和离线重放不并入分母。清单校验只有运行时检查，未请求提供商约束解码；不保证模型始终生成符合结构或引用要求的输出。

## 最终版本小样本结果

| 任务 | baseline | contract-coverage | baseline / coverage 总Token | 覆盖组清单诊断 |
| --- | --- | --- | --- | --- |
| artifact-routing | 未通过 | 通过 | 797 / 1,738 | 无效：关联未提供的旁支源码 |
| checkout-rounding | 通过 | 通过 | 1,183 / 1,589 | 无效：关联未提供的旁支源码 |
| event-replay | 未通过 | 通过 | 903 / 1,492 | 无效：关联未提供的旁支源码 |
| job-deadline | 未通过 | 通过 | 1,125 / 2,101 | 无效：引用不是精确子串 |
| pagination-cursor | 未通过 | 未通过 | 1,123 / 1,719 | 结构与引用有效，语义覆盖未验证 |

最终批次 baseline **1/5**、coverage **4/5**，两组总Token分别 **5,131 / 8,639**，覆盖组多3,508。每次一次模型调用，全部正常生成、usage完整，没有预算终止、顶层/补丁格式拒绝或基础设施错误；全部可见回归通过，成功仅由父进程目标与回归共同验收。端到端原始耗时保存在审计报告，不作为速度收益证据。

覆盖组完整修复归档规范化/优先级、金额舍入、事件租户隔离/重复处理、timeout/等待限额；分页仍只修改query.py。分页有效清单中把paging.py和query.py都标为edit，但实际只改query.py，证明引用和清单校验通过也不代表声明已落实。其余四项清单的诊断错误保留为invalid，不能用于发布已验证的行为映射。

两组同任务的实际有序证据哈希、初始工作区、任务与评分哈希一致，仅patch_policy不同；baseline的实际Prompt哈希仍与此前冻结基线一致。最终共同源码哈希 `7fd4d52c1a43eb94ac36f39e6b4ef7f26d696917fddc625bf5a39b4fafbb66ae`。全部前后模型已加载，核对Ollama0.34.3、实际窗口32,768、Q4_K_M模型digest `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`。

最终原始汇总 `.tmp/evals/patch-coverage-v1-advisory/summary-4a16176c0b.json`（同名.md），完整报告数组all-reports.json，公平条件/Token/清单诊断审计comparison-audit.json；核对脚本`.tmp/audit_patch_coverage.py`支持传入批次目录。原阻断版、离线重放及最终批次分别保存，不合并成绩。共执行两批20次真实模型调用，离线重放5份原回答，没有选择性重跑单个任务。

**结论仅为开发集单次运行的正向迹象，不能报告稳定的80%成功率或60个百分点提升。**这是整个生成提示/输出策略干预，尚未分离“先列契约”和结构化字段各自的影响；清单质量仍不足。默认仍为baseline。下一步冻结当前策略，在共同版本下五项任务每组各三次，按轮次交错运行，独立报告Token、修复和诊断清单有效率；后续再用留出任务验证，不依据本轮继续改提示。

## 复跑

```powershell
python -m pytest tests/test_patch_coverage.py -q
python -m pytest tests -q
$tasks = @('artifact-routing','checkout-rounding','event-replay','job-deadline','pagination-cursor')
for ($i = 0; $i -lt $tasks.Count; $i++) {
    $task = $tasks[$i]
    $policies = @('baseline','contract-coverage')
    if ($i % 2 -eq 1) { $policies = @('contract-coverage','baseline') }
    foreach ($policy in $policies) {
        python -m evals --suite evals/fixtures/localization-v1 --task $task --mode pipeline --search-backend keyword --patch-policy $policy --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --output ".tmp/evals/patch-coverage-replay/$task/$policy"
    }
}
```

失败返回1，保留并继续；取消后停止。使用新目录。开发者调度脚本 `.tmp/run_patch_coverage.py` 与原始产物被Git忽略，需要独立备份。Worker保存 coverage_claims、策略、原回答及实际Prompt哈希；Trace保存引用校验结果，报告仍保留独立测试与真实补丁。
