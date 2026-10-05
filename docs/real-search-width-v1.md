# 真实任务检索返回长度对照 v1

## 本次交付

真实任务入口新增 `--search-max-chars`，默认仍为 6,000；对照入口新增 `--axis search-width`，固定 full 历史策略，对比 6,000 与 3,000 字符的证据正文上限。原有 history 对照入口保持兼容。

Trace 汇总新增实际正文字符数、完整响应字符数、截断片段及每次检索的 selected/discarded 元数据。长度上限只约束代码和文档正文，不包含路径、分数、引用及 JSON 元数据；字符数不能直接视为 Token 数。

## 冻结条件

开发任务仍为 `click-flag-envvar`。本地 Ollama qwen3.5:27b、reasoning_effort none、temperature 0；预算为 12 轮、30,000 Token、16,000 上下文估计窗口、2,048 输出预留、180 秒 Worker 超时、15 秒单组验收超时。两组均 keyword 检索、full 历史，唯一 RunConfig 差异为 search_max_chars。

三组交替顺序：6000 → 3000；3000 → 6000；6000 → 3000。模型先以空 Prompt 预加载，预加载不计入修复调用。模型、Prompt、工具接口、代码、依赖、源码与独立检查冻结验证通过。

- 实现摘要：`a51cba921b5b268db479cfbad812a2df8afd1659229877e84aa93844b8fb8f80`。
- 模型 digest：`7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`。

本批次单独统计，不混入上次历史去重对照。任务已查看官方修复，只用于开发诊断。

## 实测结果

2026-10-05，三组配对、六次模型运行，提供方 usage 均可用。

| 指标 | 6,000 字符 | 3,000 字符 |
| --- | --- | --- |
| 独立验收通过 | 0/3 | 0/3 |
| budget_exceeded | 3/3 | 3/3 |
| 模型调用总数 | 15 | 17 |
| 搜索调用总数 | 6 | 8 |
| 输入 Token 总数 | 72,943 | 71,508 |
| 输出 Token 总数 | 996 | 1,107 |
| Token 合计 | 73,939 | 72,615 |
| 耗时均值 / 秒 | 16.9565 | 17.6158 |
| 返回证据正文字符总数 | 36,000 | 24,000 |
| 完整搜索响应字符总数 | 44,257 | 30,359 |
| 被截断片段次数 | 7 | 10 |
| 编辑 / 可见测试调用 | 0 / 0 | 0 / 0 |
| 源码变更 | 无 | 无 |

| 配对 | 6000 Token / 调用数 | 3000 Token / 调用数 | 验收 |
| --- | --- | --- | --- |
| 1 | 23,906 / 5 | 26,432 / 6 | 均失败 |
| 2 | 24,490 / 5 | 19,865 / 5 | 均失败 |
| 3 | 25,543 / 5 | 26,318 / 6 | 均失败 |

正文上限减半，批次 Token 合计仅低 1,324，约 1.8%；两组配对中较短组实际消耗更多 Token。短返回让两次运行多发出一次模型请求，但新步骤仍是第三次搜索，没有进入编辑。六次最终均因下一次请求预留超过剩余累计预算停止；目标检查失败、Controls 通过。

## 证据变化与解释

长度调整会改变返回证据。相同查询 `allow_from_autoenv envvar flag_value environment variable parsing` 在 6,000 组返回 5 个片段，包含 core.py 和 options.md；3,000 组返回 3 个片段，仅包含 core.py。其余候选因为证据限制未返回，或末尾正文被截断，Trace 保留位置、版本与原因。

types.py 在 6,000 组的一次运行中进入返回结果；3,000 组的两次运行通过第三次搜索才获得该文件片段。两组都只读取 core.py，没有读取 types.py 或提交修改。这些是观测到的路径覆盖，不是正式相关性标注下的 Recall 指标，也不证明未返回片段必然是修复所需证据。

本批次支持的结论：缩短单次返回能降低单次证据量，但额外搜索会抵消部分节省，尚未改善修复结果。单任务三组配对不足以确定最佳长度；模型查询和读取位置并不完全一致，不能把所有 Token 差异解释为纯文本截短效果。默认不变，不增加预算补跑成功案例。

## 验证与复跑

结果位于 `.tmp/real-defects/width-comparison-v1/freeze.json` 和 `comparison.json`，批次 completed true。chars-6000 / chars-3000 子目录保留全部工作区、任务输入、独立评分、Trace 和摘要。

相关测试 29 passed、1 skipped；全量回归 506 passed、1 skipped；Ruff 通过。新增测试验证两组只改变字符上限、交替顺序、CLI 传递以及截断/丢弃证据记录。

corecoder 环境、仓库根目录下执行，output 使用新目录，且对应准入源码和报告必须存在：

```powershell
$body = @{ model = 'qwen3.5:27b'; prompt = ''; stream = $false; keep_alive = '30m' } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:11434/api/generate -Method Post -ContentType 'application/json' -Body $body
python -m evals.compare_real_history --admission .tmp/real-defects/crossfile-admission-v2/admission.json --axis search-width --output .tmp/real-defects/width-comparison-reproduction --repeat 3
python -m pytest tests -q
```

批次退出 0 只表示对照协议完成；修复通过以 accepted 为准。单次运行可用 `python -m evals.real_tasks ... --search-backend keyword --search-history full --search-max-chars 3000`。

## 下一步

暂停继续调小返回长度，转向有限检索、局部上下文、结构化补丁的工作流诊断。现有 pipeline 按整文件选择，Click 大文件无法装入较小正文预算，不能直接照搬。先实现和离线验证基于符号边界的局部源码及依赖上下文选择，再用固定模型与预算测试能否产出候选补丁。工作流变化作为独立协议报告，不混同为检索长度的单变量收益。扩充任务与冻结留出集仍待完成。
