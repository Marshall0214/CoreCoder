# Context 去重：固定指导的三对真实运行

## 问题与预先固定的协议

验证已有 Context Builder 的 `deduplicate_reads` 是否让 Agent 更好地修复 `toolz-join-unmatched`。这是 **1 个已知开发任务、3 对重复、6 次执行**；不是 3 个独立缺陷，也不是重新评测完整 50 项或验证 Harness² 整体收益。

模型调用前已写入 [protocol.json](harness2_context_paired_20261104/protocol.json)，固定以下条件：

- 原始源码和任务描述相同；Qwen3.5:27b 的 digest、Docker 镜像、工具及评分实现哈希在前后核对一致。
- thinking=false、temperature=0、num_ctx=65536、num_predict=-1，累计 Token 只记账、不按量停止；seed 未显式设置，不承诺跨硬件逐字相同。
- 20 步、6 次编辑、1200 秒，原重复动作/连续错误阈值、候选阶段依赖读取次数及首个有效候选后停止均保持不变。
- 两组 System Prompt 附加指导和 Tool Guidance 均为空；`complete_symbols_first`、`read_index` 均关闭，仅 `deduplicate_reads` 从 false 切换为 true。
- 串行顺序：原始→去重、去重→原始、原始→去重。不根据中途分数调整顺序，不替换失败，不重试模型，不生成新的指导或策略。
- 六次执行都停止后，才统一生成独立 Target/Controls 评分；不把评分或前一轮人工诊断交给 Agent。

这是对已接入配置接口的固定策略消融；**本轮 Harness² 没有重新执行策略搜索或经验提取**，因此不能称为 Harness² 自动找到有效新策略。

## 结果

| 指标 | 原始配置 | 只开启读取去重 |
| --- | --- | --- |
| 执行次数 | 3 | 3 |
| 非空补丁 | 0/3 | 0/3 |
| Target 通过 | 0/3 | 0/3 |
| Controls 通过 | 3/3 | 3/3 |
| 两组检查同时通过 | **0/3** | **0/3** |
| 原生模型调用 | 21 | 21 |
| 原生 Token | 76,800 | 75,405 |
| 实际工具执行 / 工具异常 | 18 / 0 | 18 / 0 |
| 重复动作保护停止 | 3 | 3 |
| Agent 墙钟秒数之和 | 40.578 | 31.688 |

每个配对的原始运行均为 25,600 Token，去重均为 25,135 Token，减少 **465（1.82%）**；新增成功、成功丢失均为 0。三对重复不能证明未见任务收益或统计普遍性。

表中时间受模型预热/缓存影响：第一份原始运行 21.953 秒，另两份为 9.031、9.594 秒；后两对的单次时长接近。不将总和差异解释为稳定加速。准备、控制组、六次运行、独立评分及最终身份核对共 119.25 秒；不含后续 Langfuse 发布耗时。

本轮合计 **42 次真实本地调用、152,205 Token**，所有用量已与 6 条 Langfuse 原始推理 Trace 核对。云 API 费用为 0，本机计算成本未计价。评分覆盖自编的 Target/Controls，非完整 Toolz 测试，也不是 SWE-bench 官方成绩。

## 为什么没有推进修复

六条动作轨迹相同：

```text
列文件
→ 读取 itertoolz.py 开头
→ 搜到 join 在第 813 行
→ 按字符 offset=800 读取靠前内容
→ 再读同一位置
→ 再读同一位置
→ 第四次相同动作被保护停止
```

去重确实生效：每次候选运行改变了第 6、7 次请求，跨这两次请求合计省去 3 条重复观察；不同源码片段、任务约束和所有错误信息保留。6 份初始有效请求的哈希完全相同，排除了起始指导变化。原始组所有请求保持不变。

但这项策略只压缩已返回的观察，**不会把字符偏移改成行号、代替模型调用 read_symbol、增加新检索或改变重复动作计数器**。模型看到更少重复元数据后仍提出相同动作；未读取完整 join，未进入候选生成阶段。这一次失败发生在定位阶段，尚未走到上一轮的 iteritems 与重复输出补丁问题。

因此，当前证据支持“本例输入成本少量降低”，不支持“修复率提高”或“重复读取已解决”。保持默认配置关闭，不扩大策略或任务范围。

## 证据、复现和下一步

- [运行报告](harness2_context_paired_20261104/report.json)、[归档清单](harness2-context-paired-20261104.json)包含六次执行、补丁、原生用量、有效请求、独立评分与实现快照；原来的 110 份接入证据、64 份复盘证据和 330 份本地 42% 基线证据逐文件核对未变。
- [本地 Langfuse 对照 Trace](http://127.0.0.1:3300/project/corecoder-issues/traces/7a0a7b1805013129a1d6b2bfcea097a6)：7 个普通节点关联 6 条真实推理 Trace；比较摘要不重复产生 Generation。标签包含 experiment_id、task_id、harness_variant 及 pair。
- [运行入口](../integrations/harness2_compare.py)固定上述三对协议，目录已存在会拒绝覆盖。恢复原任务导出、既有模型、镜像与 Langfuse 前提后，使用下列命令在**新目录**复跑；每次最多六次 Agent 执行，不自动补跑或改协议。此命令不启动策略生成器。

```powershell
cd D:\project_other\CoreCoder
conda activate corecoder
$env:PYTHONPATH="$PWD\.tmp\langfuse-deps;$PWD\.tmp\workflow-deps;$PWD"
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHON_DOTENV_DISABLED='1'
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:TEMP="$PWD\.tmp"; $env:TMP=$env:TEMP
$env:CORECODER_HOME="$PWD\.tmp\harness2-comparison-state"
$env:CORECODER_LANGFUSE_ENABLED='1'
$env:CORECODER_LANGFUSE_ENV_FILE="$PWD\.tmp\langfuse-local\.env"
$env:CORECODER_TEST_BACKEND='docker'
$env:NO_PROXY='127.0.0.1,localhost,::1'
python -B -m integrations.harness2_compare --output .tmp/harness2-context-paired-new
```

相关回归 **41 passed、1 skipped**，Ruff 通过；跳过的是单独 Python 3.12 的旧控制器检查，本轮只需现有 Python 3.11，不重新安装依赖。未重复整仓测试。

**决策：本轮收尾，不继续叠加 Context 开关。**若继续研究，优先在现有指导权限内检验行号/字符偏移的理解与 `read_symbol` 使用，再固定指导做配对；只改保留顺序无法补出从未读取的函数。若以后增加结构化位置或测试反馈工具，须单独立协议，不与本次单开关比较混算。当前完整本地成绩保持 21/50（42%），历史 DeepSeek 成绩边界不变。
