# 补丁证据优先级对照 v1

## 要回答的问题

此前 staged 在三轮中均修复 2/7 个开发缺陷，但没有通过跨文件任务。本轮检查：补丁上下文的优先级是否影响修复结果，尤其阅读片段是否在字符预算内挤掉符号检索片段。

只增加 `staged_evidence_policy` 这个变量：

| 策略 | 补丁证据候选顺序 |
| --- | --- |
| read-first（原行为，默认） | 已验证的模型阅读片段，再接符号及依赖片段 |
| seed-first（可选） | 相同符号及依赖片段优先，再接已验证的模型阅读片段 |

两者都使用原 pack_fragments：逐个尝试纳入完整片段，按路径、行范围及源码哈希去重，超出 6,000 字符的片段跳过。没有截断新增片段、扩大字符预算或添加模型未读过的答案。符号证据来自公开描述和原始源码，部分符号可能因原有预算规则而不完整。优先级同时可能影响最终内容和排列顺序，本轮不拆分这两种效应。

模型、工具集合、12k 定位 / 15k 补丁 / 3k 预留预算、定位最多 4 次调用、只读权限、JSON 补丁指令、源码哈希及可见 old 文本校验、公开检查和父进程独立评分均保持原协议。原默认仍是 read-first。

## 怎么检查变量是否生效

Worker 在定位结束后保存 `staged-evidence-pool.json`，包括原始 seeds 和经源码校验的 reads；报告记录 candidate_pool_hash、evidence_hash、localization_prompt_hash、patch_prompt_hash 和 tool_schema_hash。Trace 新增 staged_evidence_selected，记录候选数量和被选片段。

候选池保存的是合法源码证据，不包括隐藏验收或上游修复。测试验证两种策略下定位请求完全相同，预算和工具相同；仅最终 fragments 改变，补丁 system 指令与其余 payload 字段不变。另有容量冲突、去重及无效策略检查。

真实试验每个策略独立运行定位，**没有重放同一条定位 Trace**。即使初始提示相同，服务执行差异也可能改变阅读动作及候选池；需逐任务核对候选池哈希，不能直接声称每次模型输入除最终证据外都完全相同。

## 冻结及复跑

协议：`evals/real_defects/staged-evidence-pilot-v1.json`。两个清单为 `staged-read-first-suite-v1.json` 和 `staged-seed-first-suite-v1.json`，RunConfig、任务和顺序完全一致，仅证据策略及清单身份不同。

本轮使用新源码版本 `462cda3e4eda5c32aa0de943e86262157697ab96e725cea7c680838a5b106b37`；保留历史结果，新版本下重新运行 read-first，不将此前 6/21 与本轮混合。固定 qwen3.5:27b，模型摘要 `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`，总预算 30k；其余配置见冻结清单。

全部 7 个 Click 开发任务，各策略先运行一次，共 14 次。顺序提前固定为 read-first、seed-first，未随机化；单轮只能提供试验线索，不能证明稳定提升。

```powershell
python -m pytest tests -q
python -m evals.real_suite --suite evals/real_defects/staged-read-first-suite-v1.json --mode live --admission original=.tmp/real-defects/mixed-original-admission-v1/admission.json --admission crossfile=.tmp/real-defects/crossfile-admission-v2/admission.json --admission expansion=.tmp/real-defects/expansion-admission-v1/admission.json --output .tmp/real-defects/staged-evidence-read-first-v1-rerun
python -m evals.real_suite --suite evals/real_defects/staged-seed-first-suite-v1.json --mode live --admission original=.tmp/real-defects/mixed-original-admission-v1/admission.json --admission crossfile=.tmp/real-defects/crossfile-admission-v2/admission.json --admission expansion=.tmp/real-defects/expansion-admission-v1/admission.json --output .tmp/real-defects/staged-evidence-seed-first-v1-rerun
```

输出须为新目录，三个准入记录共同使用此前隔离的 stdlib 环境。隐藏评分不反馈模型，失败保留在分母中，公开正常行为通过不等于缺陷修复成功。

## 本轮结果

14/14 已完成。每种策略 7 次，所有 Worker 均正常完成并产生实际修改；源码哈希、模型运行前后摘要、RunConfig、准入记录与工具 Schema 均核对一致，无未知用量、API 错误、超时、全任务预算停止或越界修改。所有配对的初始定位提示哈希相同。

| 指标 | read-first | seed-first |
| --- | ---: | ---: |
| 独立验收通过 | 2/7 | 0/7 |
| 实际修改 | 7/7 | 7/7 |
| 公开正常行为检查通过 | 6/7 | 7/7 |
| 总输入+输出 Token | 82,664 | 84,055 |
| 累计任务耗时（秒） | 154.65 | 155.77 |

| 任务 | read-first | seed-first | 真实定位候选池相同 |
| --- | --- | --- | --- |
| click-help-eagerness | 失败 | 失败 | 否 |
| click-flag-default-map | 通过 | 失败 | 否 |
| click-resource-exception | 失败 | 失败 | 是 |
| click-flag-envvar（跨文件） | 失败 | 失败 | 是 |
| click-prompt-suffix | 失败 | 失败 | 否 |
| click-invoke-missing | 通过 | 失败 | 是 |
| click-shared-default | 失败 | 失败 | 是 |

最终 evidence_hash 在 7/7 个配对中不同；选中片段的路径/行范围集合在 6/7 个配对中不同。resource-exception 的选中范围集合相同，最终顺序或元数据不同，不能将该任务描述为新增了源码内容。

另外，离线在 read-first 的每个固定候选池上应用两种策略，6/7 个任务的选中范围集合发生变化，证实优先级设置能改变被纳入的证据；这是选择器诊断，没有新增模型修复运行。

read-first 再次修复 flag-default-map 和 invoke-missing；seed-first 没有修复通过。公开检查全部通过仍不足以证明缺陷被修复。候选池相同的 invoke-missing 出现通过→失败，是值得进一步检查的线索；但当前只有一次补丁调用，不能据此判断稳定因果。候选池不同的 flag-default-map 更不能单独归因于优先级。

**决策：保持 read-first 为默认，seed-first 仅作为可选实验策略，不宣布提升。** 本轮只实现了单因素配置对照，并未严格共享定位结果。三个任务的候选池变化揭示了真实定位执行差异，下一步应冻结一份合法定位产物，让两种策略共享同一候选池与定位成本，再在独立源码副本上分别生成、评分补丁。分别记录实际补丁用量与计入共享定位成本的预算记账，不把一次共享定位计成两次实际调用。

原始产物：`.tmp/real-defects/staged-evidence-read-first-v1/`、`.tmp/real-defects/staged-evidence-seed-first-v1/`；汇总及逐任务核对：`.tmp/real-defects/staged-evidence-pilot-v1-analysis.json`。目录被 Git 忽略，需保留原始产物；本文保存统计摘要。

验证：相关测试 28 passed，全量测试 593 passed、1 skipped，改动文件 Ruff 通过。本轮全部任务为开发集；不合并历史成功率、不外推跨仓库能力，隐藏验收未进入模型输入。
