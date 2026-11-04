# SWE-bench Mini 50 项本地基线

本轮按用户要求，从已接通的一项扩展为社区 Mini 的全部 50 项：Django 25 项、Sphinx 25 项。保持 `swebench-repository-agent-v1` 策略，不先加入重复读取引导，不调用 DeepSeek 或其他付费 API。与旧项目自建 50 项及历史 94% 成绩是不同数据集。

## 固定设置

- Ollama `qwen3.5:27b`，think=false、temperature=0；推理前保存实际模型 digest。
- 每项一次尝试，20 个动作轮次、6 次编辑尝试、30,000 Token、2,048 单次输出、估算上下文 16,000、任务 deadline 1,200 秒。沿用重复动作保护。
- Mini 与官方数据 revision、文件 SHA、50 项 ID、输入清单与执行代码 SHA 在 `protocol.json` 冻结。恢复运行时拒绝混入变更后的代码或模型。
- 每项先执行未修改/参考补丁控制组；控制组不通过则记录基础设施/验收异常，不将其冒充模型失败。控制组的测试、补丁、标签不进入 Agent 上下文。
- Agent 在独立进程只接收公开字段，从固定镜像的基线 commit 搜索、读取、受约束编辑。停止后另起评分进程和隔离容器执行官方脚本、解析器及评分器，无隐藏测试反馈修正。
- `django__django-12209` 的官方 PASS_TO_PASS 列表为空。原样保留 0/0，不计算回归比例，不添加测试或伪造 100%。FAIL_TO_PASS 仍须非空。

## 资源与恢复

串行处理官方镜像，通过既有本地 HTTP 代理 7890 从官方 Registry 校验 manifest、blob SHA 和加载后的 RootFS。预先存在的镜像保留；只删除本批新加载且 ID 未改变的任务镜像，无强制删除或全局 prune。当前任务的下载 archive/blob 在成功加载后删除，元数据和校验回执保留。Docker 虚拟磁盘删除后不保证立刻缩小。

数据、缓存和依赖均在 D 盘；每项检查剩余空间，下载前额外预留展开空间。没有更改 Docker 全局设置、停止 Langfuse 或端口 8001 服务。

进度原子保存于批次目录 `report.json`，子进程日志、任务控制结果、补丁、Trace 和评分分别保存。已完成的推理不会因恢复再执行；发现中断且无完整报告的推理标为 interrupted_agent，不偷偷重新请求模型。连续三项基础设施错误暂停批次；异常任务保留在 50 项总分母中。

```powershell
# 使用既有 corecoder Python；评分依赖只注入控制进程。
$env:PYTHONPATH='D:\project_other\CoreCoder\.tmp\swebench-v5-deps;D:\project_other\CoreCoder\.tmp\swebench-deps;D:\project_other\CoreCoder'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
python -B -m evals.swebench_batch --output .tmp/swebench-mini50-baseline-20261030
# 同一冻结批次中断后恢复，已终结的任务不会自动重跑：
python -B -m evals.swebench_batch --output .tmp/swebench-mini50-baseline-20261030 --resume
```

## 结果与 Langfuse

运行期间真实推理 Trace 持续上报，包含本地模型实测 Token。批次结束后将全部 50 个任务导入同一个 Dataset/Experiment，关联原始推理 Trace 和官方评分。导入不调用模型、不复制 GENERATION；实验导入自身的延迟/Token 列不是实际推理成本，使用 `actual_total_tokens` 评分和原始 Trace。

汇总同时报告成功/50、成功/已评分、已评分数量、基础设施错误、Agent 停止原因、实际调用与已知 Token 总和。未完成、评分异常或 Token 未知均单独列明。只有 50 项全部评分完成，才能报告完整的 Mini-50 修复率；尚在运行的批次不提前写成绩。

## 2026-10-31：下载故障恢复

首轮在 7 项完成评分后，因 3 项镜像层下载未完成而暂停：官方评分 0/7，48 次模型调用、152,082 Token。失败层保留了部分文件；一次现场续传实测在 25 秒内增加 3,746,612 字节，但达到请求超时。原下载器固定尝试 18 次，即使仍有进度也会结束，这是本轮需要修复的基础设施限制。

新增 `evals.swebench_resume` 作为独立传输恢复入口，原批次冻结的 Agent、评分器和执行代码不修改。恢复先通过原代码/模型/输入哈希检查并取得同一批次锁，然后保存原报告快照、恢复代码快照及已完成任务文件哈希；只有“镜像阶段失败且没有任何推理产物”的任务重新排队。已经评分的 7 项不重新调用模型。

传输按字节进度继续重试；单次请求最多 120 秒，同一进程中单层累计最多 1 小时；连续无进展会返回外层有限重试。全部数据仍须 SHA 校验。新增至多约 12 GB 的本批共享层缓存，以硬链接复用，受限文件系统自动退回复制；缓存只服务镜像下载，不改变模型上下文或评分输入。原始 `protocol.json` 不改写，差异由 `recovery/*/admission.json` 单独记录。

```powershell
# 使用上面的 D 盘依赖/缓存环境，恢复同一冻结批次：
python -B -m evals.swebench_resume --batch .tmp/swebench-mini50-baseline-20261030
```

恢复实现相关测试 83 项通过、Ruff 通过。这个数字是代码测试数量，不是完成的修复任务数。
