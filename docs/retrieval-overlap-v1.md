# 重复检索机会与上下文开销诊断

更新：2026-10-03。目标是先确认真实工作流是否发生重复检索，再决定是否评估跨轮搜索去重。**新增自然多入口任务的 pilot 仍未触发去重，不扩大运行；目前不能判断去重修复收益。**

## 本轮交付

- 新增独立开发任务集 `evals/fixtures/retrieval-overlap-v1`，不改旧任务、Prompt、工具 Schema 或评分。
- 新任务 `lease-lifecycle`：创建租约、跨租户续租、到期清理三个入口，共享身份与生命周期契约，分别有毫秒/秒换算、租户定位、到期边界缺陷。参考修复涉及三个文件。
- 独立目标测试覆盖各缺陷及组合生命周期；可见测试验证普通路径和历史报告兼容。漏修任意一处均拒绝。参考修复与标签位于评测侧，不进入 Agent 工作区。
- 新增 `python -m evals.diagnostics`，读取 JSONL Trace，输出搜索次数、引用命中、完全相同的读取响应、搜索到读取的文本重叠及各轮请求估算。

任务是真实需求形态的人工开发案例，不是公开历史缺陷；未在任务或 Prompt 中要求再次搜索。三个入口给不同查询提供机会，但不能保证模型采用多次检索。机制验证已由固定查询测试完成，不能把强制重复搜索当成自然修复收益。

## Pilot 门槛与结果

先执行一次 full 和一次 deduplicate，固定 Qwen、关键词索引、30,000 Token、12 轮、16,000 估算上下文、2,048 输出、180 秒 Worker 和 6,000 证据字符。仅当出现实际重复搜索且去重组引用命中时，再考虑冻结更大的任务集与重复对照；两次 pilot 本身不用于声称修复效果。

| 指标 | full | deduplicate |
| --- | --- | --- |
| 状态 | budget_exceeded | budget_exceeded |
| Token | 27,599 | 27,629 |
| LLM 调用 | 6 | 6 |
| 搜索 / 文件读取次数 | 1 / 14 | 1 / 14 |
| 引用命中 | 0 | 0 |
| 源码修改 | 无 | 无 |
| 独立目标 / 可见回归 | 失败 / 通过 | 失败 / 通过 |

模型初次搜索后连续阅读四份契约及十个源码文件，随后更新计划并在修改前预算终止。没有基础设施故障、usage 缺失或选择性重跑。两组均未触发去重，不能把 30 Token 差异归因于该机制。

两次运行的源码、fixture、grader、manifest、工具 Schema 和规范化 Prompt 哈希一致。源码哈希 `9e37e582d8f4a2b9072674f86727c562c9ff0807db67703b1c77877928f834f9`；此后只补充离线诊断统计及测试，未追加模型运行。Prompt 哈希 `9e4c89e5355f8f18ab05ca7f25d27786ae880c8e41af2907726ef3d0bb89163e`。

原始汇总（同名 JSON 保存配置、版本、测试和用量）：

- [full pilot](../.tmp/evals/retrieval-overlap-v1/pilot/full/summary-8f1dc6adb8.md)
- [deduplicate pilot](../.tmp/evals/retrieval-overlap-v1/pilot/deduplicate/summary-22d64c6870.md)

## Trace 诊断：重叠发生在哪里

| 观测指标 | 旧 search-history-v1 的 30 次 | 本轮 2 次 pilot |
| --- | --- | --- |
| 搜索 / 读取总数 | 30 / 196 | 2 / 28 |
| 完全相同的重复读取响应 | 0 | 0 |
| 包含此前同路径搜索正文的读取次数 | 144 | 20 |
| 这些读取中的重叠正文字符 | 41,638 | 5,782 |
| 各轮请求输入估算范围 | 2,461–5,258 | 2,496–6,788 |

读取去除工具行号前缀后，与此前该路径的非空搜索正文精确匹配；同一次读取中重叠区间只计一次。不同路径的相同文本不计入搜索/读取重叠；不计空引用。统计表示“先前曾返回过的文本”，不确认该文本此刻仍在压缩后的模型历史中，也不是可直接省去的 Token 数。

原协议要求读取完整文件后才能编辑，因此搜索片段与读取重叠是预期行为。14 个文件各读一次已经使输入增长，不必发生相同工具的重复调用。应研究“保留完整读取时，如何替换已有片段或压缩冗余历史”，而不是简单取消必要阅读。当前数据尚不能按组件归因累计输入 Token，也不能证明去重这些文字会改善修复。

## 复跑与验收

```powershell
python -m pytest tests/test_overlap_tasks.py tests/test_trace_diagnostics.py -q
python -m evals.diagnostics .tmp/evals/search-history-v1 --output .tmp/evals/retrieval-overlap-v1/prior-trace-diagnostics.json
python -m evals.diagnostics .tmp/evals/retrieval-overlap-v1/pilot --output .tmp/evals/retrieval-overlap-v1/pilot-trace-diagnostics.json
```

新任务完整修复通过、每个不完整修复被拒绝；诊断测试检查同路径匹配、重叠不重复计数和空 Trace。最终全量回归 **255 passed、1 skipped，47.57 秒**；新增代码 Ruff 与 `git diff --check` 通过。Windows 符号链接测试继续跳过。原始产物位于 Git 忽略的 `.tmp/evals/retrieval-overlap-v1/`，需独立备份。

Pilot 复跑（PowerShell，若需新实验请使用新输出目录）：

```powershell
foreach ($pilotHistory in @('full', 'deduplicate')) {
    python -m evals --suite evals/fixtures/retrieval-overlap-v1 --mode live --model qwen3.5:27b --base-url http://localhost:11434/v1 --reasoning-effort none --search-backend keyword --search-history $pilotHistory --output ".tmp/evals/retrieval-overlap-v1/pilot/$pilotHistory"
}
```

退出码 1 表示至少一个任务未验收通过，不能误作基础设施故障；仍检查完整报告。当前没有去重触发，不建议原样增加重复次数。

## 下一项独立实验

先补充每轮消息角色、工具正文/元数据、历史保留与压缩的输入开销记录；在调用前估算与提供商 usage 间明确区分。随后设计搜索片段被完整文件读取覆盖时的历史替换策略，保留版本和行号，验证文件变化、压缩、历史丢失与错误恢复。

这是新的上下文组织干预，应使用共同版本、固定模型与预算重跑，不能与本轮跨搜索去重混合归因。先以小样本确认干预实际发生；成功后才开展完整对照。当前不修改旧协议、不提高预算、不宣称收益。
