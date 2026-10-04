# evidence-width-v1：检索种子数量对照

日期：2026-10-04。在 bounded-pipeline-v1 中固定路径排序、提示与预算，只改变检索种子 K=5 / K=10；先核对真实证据变化，再决定是否调用模型。

## 离线干预检查

新增 Trace 字段 ranked_chunks、candidate_files、seed_count，区分请求 K、正分候选文件数量与实际种子数。BM25 当前只保留正分结果，不为凑满 K 自动加入无匹配文件；沿静态依赖扩展得到的最终文件数可以大于种子数。

| 任务 | 正分候选文件 | K=5 种子 / 最终文件 / 正文字符 | K=10 种子 / 最终文件 / 正文字符 | 干预 |
| --- | --- | --- | --- | --- |
| pagination-cursor | 2 | 2 / 5 / 1,563 | 2 / 5 / 1,563 | 未生效：不调用模型 |
| lease-lifecycle | 7 | 5 / 8 / 2,054 | 7 / 10 / 2,676 | 生效：六次交错运行 |

分页两组的排序后证据与正文完全相同，不能用于估计扩大范围的效果。中文缺陷描述与英文源码的词项匹配有限，固定查询后缀也会影响候选分布；候选不足的根因还需独立查询/召回诊断，不能把 K=10 当作全部源码控制组。

租约 K=10 新增 docs/cleanup.md 与 docs/renewal.md，已有文件的内容和哈希不变；预算未丢弃文件。两组已有三处缺陷源码及主要契约，增加 K 不代表原先漏召回缺陷文件。测试、标签、参考修复不进入证据。

## 冻结协议

Qwen3.5:27b Q4_K_M、temperature=0、reasoning_effort=none、路径排序、K=5/10、依赖深度=2、正文 6,000 字符、Token 30,000、输出 2,048、估算上下文 16,000、Worker 180 秒、测试 15 秒。每次干净工作区、一次模型调用、父进程独立验证。第 1/3 轮 K5→K10，第 2 轮 K10→K5；每组三次，不合并历史结果，不因失败重跑。

这是单个人工开发任务的探索性对照；不支持真实仓库泛化、统计显著性或默认扩大 K。未清空 Ollama 缓存，耗时用于记录，不用于宣称优化收益。

## 实际结果

| 任务 | K | 独立通过 | 每次输入 / 输出 / 总 Token | 端到端秒数（按重复轮） |
| --- | --- | --- | --- | --- |
| lease-lifecycle | 5 | 3/3 | 1,338 / 554 / 1,892 | 28.50、28.92、28.00 |
| lease-lifecycle | 10 | 3/3 | 1,630 / 568 / 2,198 | 29.70、28.71、28.42 |

两组都修复 acquire.py、expiry.py、lookup.py，补丁相同，未增加防御性编辑。K10 每次多 306 个总 Token，其中输入多 292、输出多 14；本任务没有观察到修复收益，不据此泛化为所有任务扩大 K 无效。分页只做离线证据检查，未执行本轮真实模型运行，不能新增分页成功率结论。

六次均一次调用、正常完成、usage 完整，无基础设施错误或预算终止。两组配置仅 evidence_top_k 不同，源码、初始工作区、任务与评分哈希一致；同组实际 Prompt 与证据哈希一致，新增文档之外的文件正文完全相同，未丢弃文件。源码哈希 `1729ecb8af3fb41a2959c2bbc250ebb54a995d96f31ca122f556f8a224ff4402`。每次前后模型已加载，核对 Ollama 0.34.3、实际窗口 32,768、同一模型 digest `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`。

完整汇总 `.tmp/evals/evidence-width-v1/summary-a50a5e867e.json`（同名 .md），报告数组 `all-reports.json`，配置和证据核对 `comparison-audit.json`，核对脚本 `.tmp/audit_evidence_width.py`；每次原输出、Trace、补丁及验收记录在 run_id 目录。测试 **305 passed、1 skipped**（Windows 符号链接环境）；Ruff、git diff --check 通过。

**保留默认 K=5。**本轮无法解释分页全部公开证据诊断与有限证据修复之间的差异，因为分页 K 干预未生效。下一步建立离线检索质量评测，分别衡量初始种子召回与依赖扩展后的缺陷源码覆盖；相关标签仅供评分，不进入查询、索引或模型。先覆盖现有开发任务，再根据失败类型选择查询或语义检索改造，避免继续只改 K。

## 复跑

```powershell
python -m pytest tests -q
foreach ($rep in 1..3) {
    $widths = @(5, 10)
    if ($rep -eq 2) { $widths = @(10, 5) }
    foreach ($width in $widths) {
        python -m evals --suite evals/fixtures/retrieval-overlap-v1 --task lease-lifecycle --mode pipeline --search-backend keyword --evidence-order path --evidence-top-k $width --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --output ".tmp/evals/evidence-width-replay/$rep/k$width"
    }
}
```

新实验用新目录，保留失败，取消后停止。开发者调度与离线检查脚本分别为 `.tmp/run_evidence_width.py`、`.tmp/preflight_evidence_width.py`；离线证据 manifest 在 `.tmp/evals/evidence-width-v1/preflight/manifest.json`。脚本和原始产物被 Git 忽略，需独立备份。上述 CLI 复跑各次独立批次，重复轮以目录标识。
