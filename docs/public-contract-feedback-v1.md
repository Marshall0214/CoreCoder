# 公开契约检查与有限反馈

## 目的

覆盖清单只能核验引用、结构和改动声明，不能证明行为正确。本工作流把公开描述和选中的源码转成可执行检查，以发现候选补丁的行为遗漏；最终成功率仍由父进程的隐藏目标测试和原有回归测试决定。

## 协议

新增 `--mode contract-feedback`，报告协议为 `public-contract-feedback-v1`；原来的 `pipeline` 单调用协议保持不变。

1. 按既有关键词检索、静态依赖展开和字符预算选择证据。
2. 模型仅接收公开描述、允许文件名及选中证据，生成 unittest 检查。冻结代码、内容哈希和生成提示哈希，再在原始代码副本上执行。
3. 使用同一证据进行初次修复。检查文件不写入候选工作区，不允许补丁修改。
4. 在候选代码的新副本上运行冻结检查。仅当原始代码和候选代码都出现断言失败，且无测试错误、超时或检查文件变化时，发送一次反馈修复。
5. 反馈包含冻结检查和最多 6000 字符的检查 stderr；重新读取原先选中的文件，更新内容哈希。修复后再检查一次，无循环重试。
6. 父进程最后独立验收。隐藏测试、参考补丁及隐藏失败信息不进入模型请求。

通常两次模型调用（生成检查、初次修复），最多三次。所有调用共用原有 Token/上下文预算，所有执行受 worker 总时限和单次测试时限约束；检查次数、执行耗时和原始日志单独保存。无效生成会记录原因并继续初次修复，不能把无效检查视为通过。

## 验证与复跑

```powershell
python -m pytest tests/test_contract_feedback.py -q
python -m pytest tests -q
python -m evals --suite evals/fixtures/localization-v1 --mode contract-feedback --task checkout-rounding --task pagination-cursor --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --evidence-order path --patch-policy contract-coverage --output .tmp/evals/public-contract-feedback-v1-final-pilot
```

查看各运行目录的 `worker-result.json` 中 `public_checks`、`feedback_attempts`、`patch_stages`，以及 `trace.jsonl`、`public-contract-checks.py`、`public-*.stderr.txt`。最终结论看 summary 的 `accepted` 与 `verification`，不以生成检查通过替代独立验收。

## 2026-10-05 机制验收

离线验证：13 项新增测试通过；全量 **348 passed、1 skipped**；改动的运行时与测试文件 Ruff 检查通过。包括冻结检查、刷新源码哈希、单次反馈上限、生成失败、导入错误、零测试发现，以及错误公开检查不能覆盖隐藏验收。

先固定两个试点任务：金额舍入（此前通过的正向对照）与分页（此前遗漏行为的失败案例）。Qwen `qwen3.5:27b`、temperature 0、reasoning none；每次输出 2048 Token、累计 30000 Token、上下文估计 16000、worker 180 秒、测试 15 秒；keyword K=5、依赖深度 2、证据 6000 字符、path 顺序、contract-coverage 修复策略。

初版报告 `.tmp/evals/public-contract-feedback-v1-pilot/summary-d104804899.json`：两项独立验收通过；金额测试生成达到输出上限导致 JSON 截断，未执行公开检查，消耗 4841 Token；分页 12 项检查在原始代码和初次补丁上失败，经一次反馈后通过，三次调用共 9245 Token。该版本单列，未修改原报告。

随后只将生成要求收紧为最多六个精简测试、代码建议少于 4000 字符，不提高预算。最终报告 `.tmp/evals/public-contract-feedback-v1-final-pilot/summary-80e8d7076f.json`：

| 任务 | 有效冻结检查 | 初次补丁公开检查 | 反馈次数 | 最终公开检查 | 独立验收 | 总 Token |
| --- | --- | --- | --- | --- | --- | --- |
| checkout-rounding | 6 | 失败 | 1 | 失败 | 通过 | 5878 |
| pagination-cursor | 6 | 失败 | 1 | 通过 | 通过 | 7266 |

最终两项均三次调用，usage 完整，无预算终止，共 13144 Token。分页反馈后补充了分页模块的修改，冻结检查与独立验收均通过；这是机制可运行的证据，尚不能证明稳定提升或归因于反馈本身。

最终共同源码哈希 `5eddb729245e569be2830efbc7e4b4da08242b4e262024e4f0710acbaf170660`；金额/分页总耗时分别 56.28/72.33 秒，公开检查三轮累计执行 0.25/0.24 秒。初版源码哈希 `a716612b92d17c343192940436f8a1c4f7ec7cde5a8a13dbf89bf80c0d796370`，两版不合并计算成功率。

金额检查存在错误期望：`100 minor × 5 bps / 10000 = 0.05`，ROUND_HALF_UP 后应为 0，生成测试却期望 1；`300 minor × 10 bps / 10000 = 0.3` 应为 0，却期望 30。初次补丁已修改金额和折扣模块，反馈再次改写折扣实现，最终仍通过独立验收，但错误检查继续失败，说明反馈会增加无效开销。保留该失败，未手工改测试或重算成绩。

当前保持可选工作流，不修改默认单调用基线。下一步先改进公开检查期望值的可核验依据，再做冻结共同版本的有/无反馈对照。`.tmp/` 被 Git 忽略，原始报告、检查、补丁和 Trace 应独立备份。

## 解释边界

模型生成的期望值可能错误，检查可能缺少关键边界或发现零个测试。导入/语法错误不作为业务失败反馈；原始代码通过的检查也不触发反馈。冻结检查只能避免修复阶段改测试，不能证明检查完整或正确。

检查执行在可信合成任务的临时副本中，清理环境变量并设置时限；AST 校验不是操作系统安全沙箱，不能直接用于不可信仓库。临时副本不包含父进程的隐藏测试，但该限制不构成宿主文件系统隔离保证。

与单调用基线相比，新增调用和执行机会均有变化，不能据此声称检索策略带来提升。当前只做机制试点；后续需冻结共同版本，设立有/无反馈的相同检查生成对照，再扩展任务和重复次数。
