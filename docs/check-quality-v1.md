# 检查质量诊断与路由契约版本化

## 离线诊断

新增 `python -m evals.check_quality`，只读取已完成的 report.json，不调用模型、不执行生成代码、不修改测试或原始报告。输出每次运行的缺陷检测观察、最终公开检查结果和独立验收冲突，并按协议、任务文件哈希及源码哈希分组，避免合并不同版本成绩。

- `detected`：在原始工作区实际执行了至少一项冻结检查，出现断言失败。它不证明断言正确或精确命中目标缺陷。
- `missed`：原始工作区的冻结检查全部通过，未识别该任务的已知缺陷。
- `unknown`：没有执行、生成失败、超时、执行错误、零测试、检查变更或结果字段不一致。不能算作检出，也不能当作实测通过。
- `accepted_patch_conflict`：父进程独立验收通过，但最终公开检查发生断言失败。独立验收覆盖也可能不足，因此只标记需要契约复核，不能自动断定检查错误或补丁完全正确。

存在 final 执行时优先使用它，不用通过的初次 candidate 掩盖最终失败。重复 run_id 的相同报告去重，内容冲突则报错；记录报告绝对路径和 SHA256，输出目录已存在时拒绝覆盖。没有公开检查的基线报告不进入检查质量分母。

契约歧义需要人工审阅公开规格，本工具明确记录为 `not_automatically_determined`，不根据隐藏验收自动判断歧义。所有诊断是父进程事后分析，不能用于挑选检查、修改历史成绩或反馈给模型。

```powershell
python -m evals.check_quality --input .tmp/evals/localization-workflow-comparison-v1 --output .tmp/evals/check-quality-v1-replay/frozen-comparison
python -m evals.check_quality --input .tmp/evals/check-surface-v1-pilot-final --output .tmp/evals/check-quality-v1-replay/surface-pilot
```

本次诊断结果保存于 `.tmp/evals/check-quality-v1` 的 frozen-comparison、surface-pilot 和 clarity-pilot 子目录，均包含 quality.json 与 quality.md。

| 来源 | 有公开检查记录的运行 | 检出观察 | 未检出 | 未知 | 与独立验收通过补丁冲突 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 冻结 v4 完整对照 | 15 | 9 | 3 | 3 | 3 |
| v5 观察边界三项试点 | 3 | 2 | 1 | 0 | 1 |
| 明确路由契约的 v2 试点 | 1 | 1 | 0 | 0 | 0 |

v4 的三次未知来自路由导入违规；三次未检出和冲突来自事件状态断言。v5 未检出仍为事件任务，冲突来自路由的 `..` 期望。三组来自不同协议/源码/任务版本，表格用于描述问题，不构成效果提升对照。

## 路由任务 v2

另建 `evals/fixtures/contract-clarity-v2/artifact-routing-v2`，明确逻辑仓库路径的规则：规范化分隔符并删除空段及单点 `.`；双点 `..` 保留为字面段，不进行文件系统父目录遍历。同一规则作用于输入路径和匹配模式。

公开契约含正反例；新增可见规范化回归和父进程匹配验收，覆盖 `..` 字面匹配、与 `.` 模式不匹配、Windows 分隔符及优先级组合。原始缺陷和两处参考补丁不变。新任务属于合成开发集，不是留出集。

旧 localization-v1 未修改；测试核对旧任务完整文件哈希仍为 `df3bdd537e6ef4d387c1f8cbcd2ead2d33239b125238da5bfe2e004b2a0c1c81`。v1/v2 任务 ID、目录和哈希不同，旧实验结果原样保留。

## 验证与试点

新增诊断与任务验收测试共 16 项通过；最终完整回归为 447 passed、1 skipped，Ruff 和 diff 检查通过。新版任务 unchanged 独立验收失败，可见回归通过；reference/scripted 均通过目标验收及可见回归。

```powershell
python -m pytest tests/test_check_quality.py tests/test_contract_clarity_tasks.py -q
python -m pytest tests -q
python -m evals --suite evals/fixtures/contract-clarity-v2 --mode contract-feedback --task artifact-routing-v2 --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --evidence-order path --patch-policy contract-coverage --public-check-policy contract-surface --output .tmp/evals/contract-clarity-v2-replay
```

一次 Qwen 本地试点：生成及审查有效，保留 6 项检查；原始代码断言失败，初次补丁后公开检查和独立验收均通过，0 次反馈、3 次模型调用、5,296 Token。原始结果为 `.tmp/evals/contract-clarity-v2-pilot/summary-97d54744d4.json`。源码哈希 `e5f6df452102589db5d8e4ba3864fc32a8454f561c25b70cd8845b0f738b4e9a`，报告任务哈希 `fa922504243a32cf645e127de5a883684864e55271821a232b3c35e94d16dd14`。

生成检查包含双点字面匹配，但没有独立覆盖“双点输入不匹配单点模式”的反例；后者由新版父进程验收覆盖。因此这一次结果只证明澄清后该试点没有再发生原有冲突，不证明生成检查完整，也不能与旧任务的 Token 直接比较。原始实验及诊断目录被 Git 忽略，需另外备份。

下一步优先补充基于公开事件契约的跨租户同 ID、批次中途重复和多批次重放检查，评价是否识别原始缺陷、是否与独立通过补丁冲突。检查质量稳定后再考虑按需验证成本与真实缺陷留出集。
