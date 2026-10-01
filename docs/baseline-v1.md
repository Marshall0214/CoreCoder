# baseline-v1：受限 CoreCoder 人工任务初始基线

运行日期：2026-10-01。由用户在本机执行；本记录从实际 JSON 报告汇总，未重新调用模型。P0-1 闭环验收完成。

## 验收与复现

用户验证新增测试 24 passed（13.67 秒）、全部测试 203 passed（30.19 秒）。unchanged 为 0/5，reference 和 scripted 均为 5/5；真实单项 timeout-units 通过。reference/scripted 不计入模型效果。

正式运行命令：

```powershell
python -m evals --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --repeat 3 --output .tmp/evals/baseline-v1
```

代码 commit：`e2666893eae072f55ea9033a93af27bbf2e0df27`。15 份报告均记录工作树干净、相同实现哈希和工具 Schema 哈希。Python 3.11.16；openai 3.20.0、rich 15.0.0、python-dotenv 1.2.3。

- 实现 SHA256：`8e324a7fdc49378fb0b3b613250502209bc9220a9ddf81c76f8619be34b982f4`
- 工具 Schema SHA256：`20b9fe09cc80a4f2adb00c48656398cd0d61cbe46deb48811cdfe434792c25ee`
- Ollama：0.34.3；模型 qwen3.5:27b，27.8B，Q4_K_M。
- 模型 digest：`7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`
- 生成参数：temperature=0，reasoning_effort=none，单次输出 2,048 Token。
- 预算：12 轮、30,000 Token、Worker 180 秒、每组测试 15 秒。
- 评测侧上下文估算限制 16,000 Token；Ollama 实际加载窗口均为 32,768。

任务与目标测试哈希、每项 Prompt 哈希、完整配置和模型加载信息见各 report.json。执行方式为受限 CoreCoder：固定 7 个工具、按调用顺序执行、只允许运行可见 unittest 命令。并非原版全部功能的无约束基线。

## 实测结果

| 任务 | 验收成功 | 平均总 Token | 平均端到端秒数 |
| --- | --- | --- | --- |
| falsey-overrides | 3/3 | 8,883.0 | 24.31 |
| inclusive-date | 3/3 | 9,142.7 | 24.20 |
| retry-policy | 3/3 | 8,919.3 | 22.66 |
| tenant-cache | 3/3 | 9,106.0 | 23.15 |
| timeout-units | 3/3 | 9,066.7 | 24.79 |

共 5 个独立任务、15 次运行，验收成功 15/15（100%）；每次目标与回归测试均通过。每次均为 4 次 LLM 调用、5 次工具调用。没有观察到修复、预算或基础设施失败。

- Prompt Token 总计 129,689；Completion Token 总计 5,664；总计 135,353。
- 每次平均总 Token 9,023.5，中位数 9,070；15 次均有 usage，无缺失。
- 每次端到端平均 23.82 秒，中位数 23.68 秒，范围 22.27–27.56 秒。
- 逐任务端到端耗时合计 357.32 秒，包含各自准备、Worker 和独立验收，不代表整条 CLI 的精确墙钟耗时。
- 费用未核算，保留 null；本地计算资源成本没有测量。

第一项运行前模型尚未加载，后续可能存在加载/前缀缓存收益；未统一冷缓存，也未交错策略，不把本次耗时作为严格性能比较。所有任务均成功，因此成功任务与全部任务的均值相同。

## 证据与冻结范围

原始汇总：[Markdown](../.tmp/evals/baseline-v1/summary-8081c618ff.md)、[JSON](../.tmp/evals/baseline-v1/summary-8081c618ff.json)。运行目录包含完整补丁、Trace、候选代码及目标/回归测试输出。`.tmp/` 被忽略；文档提交不会保存原始证据，需由用户备份整个 baseline-v1 目录。

本基线冻结为人工任务 v1 与上述执行条件的历史记录，不覆盖原始结果。更改任务、工具、Prompt、模型或预算时创建新版本，并说明干预变量；后续共同任务的对照需要使用同一版任务和执行条件。

## 结论与下一步

本次证明独立修复与评分闭环可运行，且这 5 个简单任务在重复运行中均成功。15 次运行仍只有 5 个独立任务；结果不代表真实仓库修复成功率，也没有证明检索收益或优于其他产品。

当前任务结果出现满分，不能用它们单独衡量检索对成功率的改善。保留这些任务作为回归集，P0-2 首先增加包含干扰文件、非显式定位线索及跨模块契约的开发任务，再建立统一 search_code 和关键词检索对照。检索策略实现后需要重新生成公平的共同协议基线；公开历史缺陷和留出集用于最终结论。
