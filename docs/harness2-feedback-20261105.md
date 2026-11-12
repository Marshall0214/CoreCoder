# Harness² 与公开反馈修正接通（2026-11-05）

## 执行入口

`integrations.harness2` 增加显式 `--public-feedback`：每个 base/invariant/domain/composition 探测在原有候选生成之后继续公开验证和修正，再向 Harness² 返回最终补丁及公开行为记录。未带开关时仍使用原流程；历史实验不被自动重跑或改写。

```text
Harness² 选择一份指导与 Context 配置
  → 自有 Agent 定位代码、生成初始候选
  → 在完整源码副本上重建候选
  → 静态检查 + Docker Reproduce / Preserve
  → 本地 LLM 根据公开错误修正，最多 20 次请求
  → 将最终 Diff、公开结果与修正轨迹返回 Harness²

所有探测、采纳及反思结束后 → 控制端独立评分
```

20 次是反馈修正请求数，不是原探索器的工具动作数。格式错误、无变化和重复失败都计入并保留，不按重复次数提前终止。每个反馈阶段默认 1,200 秒，初始探索阶段仍保留原有 1,200 秒，因此新流程不声称与旧流程总预算相同；子进程等待额度相应增加。只统计 Token，不做应用层 Token 预算截断；本地 Qwen3.5:27b、thinking 关闭。

模型只接收公开 Issue、当前可写源码、冻结指导和公开诊断。可写集合沿用执行器判定的全部既有可写文件，不根据参考答案挑选目标。Context 三项配置在反馈请求中继续应用；完整文件读证据随每次改动刷新。反馈阶段当前要求直接返回结构化补丁，没有另开搜索工具循环，因此属于完整链路的第一版接入，不代表工具使用设计已经与探索阶段完全统一。

初始 `agent/` 制品不覆盖；反馈及最终候选保存到 `feedback/`，`execution.json` 指定最终制品。Adapter 的交付、可见轨迹和后验评分都读取同一个最终候选。编辑器可看公开反馈，不能看到后验 Target/Controls；验证器、测试、权限和模型配置不在可编辑范围。

## 导出集对齐

本次 Toolz 原始导出含 75 份文件，原 Agent 过滤后收到 65 份。遗漏的 10 份配置/构建文件不是删除补丁。接入层先校验 `baseline-files.json`、原补丁哈希及候选文件差异，再把真实修改叠加到完整原始导出，保留这 10 份文件。未声明改动、测试修改或不一致候选会被拒绝。

## 两种运行方式

在已有本地依赖、Docker 和模型环境中，用 Python 3.12 控制器调用。子进程继续使用已有 Python 3.11 `corecoder` 环境；`TEMP/TMP/CORECODER_HOME` 等位置均在 D 盘。Docker 命名管道需要执行环境具备访问权限，不能以宿主机测试替代。

新开一轮完整 PPC 搜索（本次未执行此命令）：

```powershell
& 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m integrations.harness2 --context-policy --public-feedback `
  --feedback-rounds 20 --output .tmp/harness2-feedback-full-20261105
```

验收单项冻结策略，不再做提议/合成：

```powershell
& 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m integrations.harness2_feedback `
  --from-trial .tmp/harness2-autonomous-20261104 `
  --reuse-rollout --feedback-rounds 20 `
  --output .tmp/harness2-feedback-20261105-v3
```

这条命令使用真实 Adapter，复用已生成的 agg1 候选，执行新公开反馈，再由控制端评分。去掉 `--reuse-rollout` 会重新从原始源码执行一次初始 Agent，再继续反馈；仍不会启动新策略搜索。

复用时原报告和原模型用量完整保留，`reuse.json` 声明来源；新增调用只计反馈阶段。不会把原有 11 次生成调用再次计入本轮，也不把保存候选说成重新生成的基线。

## 验收记录

相关 Python 3.11 测试已通过 **68 passed、1 skipped**；Python 3.12 单独通过控制器 **10 项**测试。Ruff 已通过。测试覆盖开关兼容、固定公开检查、指导/Context 传递、导出集补全、原始报告保留、复用成本去重、未知用量以及终止后候选篡改拦截。

真实验收完成，使用冻结 agg1 和本地 Qwen，thinking 关闭：

| 阶段 | 模型修正 | 静态问题 | 公开复现 | 公开保持性 | 本轮 Token |
| --- | --- | --- | --- | --- | --- |
| 第 0 轮 | 保存的失败候选，未重新生成 | 2 处 `iteritems` 未定义 | 0/2，NameError | 3/3 | 0 |
| 第 1 轮 | 将两处 `iteritems(d)` 改为 `d.items()` | 0 | 0/2，重复输出 | 3/3 | 41,515 |
| 第 2 轮 | 将公共末尾循环缩进到 Full Join 分支，与 Left Join 分支互斥 | 0 | 2/2 | 3/3 | 41,397 |

反馈阶段 **95.453 秒、2 次真实调用、82,912 Token**（输入 81,952，输出 960），两次补丁均由模型产生并通过工具校验应用，未提供人工诊断补丁。第 1 轮仍失败，第 2 轮通过后自动结束，没有强行跑满 20 轮。最终仍有 AST 重复循环审查提示，但两个循环处于互斥分支，因此不自动拒绝；行为测试决定本次公开准入结果。

本次每轮提供旧工具规则判定的全部 20 份可写 Python 文件（包含包源码及示例/文档代码），未利用参考补丁缩小到目标文件。这样上下文充分但输入较大；当前交付只验证流程有效性，尚未优化反馈阶段的上下文成本。

终止后独立评分：**Target 1/1、Controls 1/1**。初始候选在历史独立评分中失败，原候选及报告经哈希和 Diff 重建核对；本轮没有另跑一个新的无反馈对照组。这个已知开发任务说明反馈修正机制能够工作，不能据此认定 Harness² 搜索策略提高整体修复率，也不是留出集或 SWE-bench 成绩。公开检查和独立评分仅覆盖配置的案例，不等于 Toolz 全套上游测试。

Langfuse 已回读核验两次 Generation 的单轮及汇总用量，推理轨迹共 5 个节点。另发布 [终止后的关联摘要](http://127.0.0.1:3300/project/corecoder-issues/traces/2c3238182c1843dc060ca399c6931eb9)，链接 [真实反馈推理](http://127.0.0.1:3300/project/corecoder-issues/traces/62c72148ebfd45ad9f13a8f08497fba3)和历史候选轨迹；摘要 4 个普通节点、0 个 Generation，不伪造新模型调用。独立结果只在后验摘要中展示，没有返回模型或编辑器。

后验摘要入口为 `python -B -m deploy.langfuse.harness2_feedback --output .tmp/harness2-feedback-20261105-v3`，使用现有 D 盘 Langfuse SDK 及本地配置；发布过程不调用模型。逐文件哈希及可提交制品见 [证据清单](harness2-feedback-20261105.json)。

启动记录均保留：首个目录因 Docker 管道权限受阻，第二个目录暴露导出集差异；两次均在模型调用前停止。修正后使用全新 `v3` 目录，不覆盖原始失败制品。
