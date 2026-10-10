# 统一 Issue 修复流程：演示与复现

## 当前交付

CLI 与 FastAPI 的 `repair-approval-v1` 共用 `repairflow.engine.execute`：

```text
可信任务包 → 执行计划审批（API）→ 隔离源码副本
→ 目标/关联方法检索 → LLM 结构化补丁 → 锚点、范围、实际变更及语法校验
→ 公开/冻结行为检查 → 必要时最多一次反馈修正
→ 独立 Target/Controls 验收 → 结果报告、补丁与 Trace
```

最新目标覆盖检索与补丁约束被接入统一入口；运行时反馈与回滚逻辑整理到 `repairflow/`，复用版本化检索和补丁实现，未修改历史冻结实验。新检查执行器使用当前 Python 的 `-I -B` 子进程、相同测试分组和判定规则，不再依赖旧实验专用虚拟环境。历史 47/50 成绩不因本次集成而改写；不同解释器的依赖环境仍须记录与核对。

任务审批针对**是否开始执行**，发生在推理前；最终补丁保留在任务副本供下载审查，不写回用户源码。尚未实现生成后合并审批、任意 GitHub 仓库接入或每任务容器沙箱。

## 1. 环境与 D 盘路径

在 `D:\project_other\CoreCoder` 的 corecoder Conda 环境执行。干净环境需安装项目已有的 service/workflow extras；本机 SQLite 检查点扩展已在 D 盘，下列变量沿用该目录：

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = 'D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp'
$env:TMP = $env:TEMP
$env:RUFF_CACHE_DIR = 'D:\project_other\CoreCoder\.tmp\ruff-cache'
$env:CORECODER_REPAIR_BUNDLES = 'D:\project_other\CoreCoder\.tmp\repair-bundles'
```

本流程从源码 checkout 运行；当前 wheel 仍只包含 corecoder，并未把完整实验依赖打包为独立发行版。不需要修改已有 8001 服务。

## 2. 生成独立任务包

首次导出使用本机已冻结的 50 项 manifest；导出后运行只依赖任务包，不再读取历史 manifest 或参考修复：

```powershell
python -B -m repairflow prepare --task click-usage-empty --output .tmp/repair-bundles/click-usage-empty --include-replay
```

已有相同目录可直接复用；导出和运行都拒绝覆盖旧产物。任务包保留原源码及许可证，包含公开检查、冻结检查、独立评分和哈希；**不包含参考修复源码**。独立评分不会进入模型请求。任务包是本地可信、可执行测试资产，不是可接收不可信上传的格式；哈希用于完整性校验，不提供来源签名。

`--include-replay` 仅允许最近完整评测中一次调用成功的任务，绑定历史完整请求哈希、回答与用量；不支持把多轮反馈中变化的时间日志伪装成精确回放。

## 3. 一条命令完成离线验收

```powershell
python -B -m repairflow demo --bundle .tmp/repair-bundles/click-usage-empty --output .tmp/repair-demo/my-demo-001
```

该命令先运行 CLI 引擎，再通过 ASGI HTTP 客户端驱动真实服务 Worker：幂等提交、待审批、关闭/重建服务、恢复同一审批、批准、修复、独立验收、SSE 和制品下载，最后验证拒绝审批不执行。CLI/API 补丁必须逐字节相同。

结果查看 `acceptance.json` 和 `evidence/`。这是**历史回答回放验收**，真实检索、应用和测试都会重新执行；新模型请求为零，历史 Token 用量明确标记，不能计作新的修复率实验。ASGI 客户端不监听浏览器端口，Worker 是真实子进程。Windows 沙箱若限制本地 socketpair，需在允许本地网络的终端运行。

只运行 CLI：

```powershell
python -B -m repairflow run --bundle .tmp/repair-bundles/click-usage-empty --mode replay --output .tmp/repair-demo/my-cli-001
```

## 4. 浏览器/API 演示

第一个终端启动独立端口，DeepSeek 最长任务用 1,200 秒服务超时：

```powershell
python -B -m service --port 8004 --timeout 1200 --output .tmp/repair-demo/http-service
```

浏览器打开 `http://127.0.0.1:8004/docs`；或第二个配置相同环境的终端执行：

```powershell
$base = 'http://127.0.0.1:8004'
Invoke-RestMethod "$base/catalog"
$body = '{"suite":"repair","task_id":"click-usage-empty","mode":"replay","workflow":"repair-approval-v1"}'
$task = Invoke-RestMethod "$base/tasks" -Method Post -ContentType application/json -Headers @{'Idempotency-Key'='demo-001'} -Body $body
do {
    Start-Sleep -Milliseconds 300
    $state = Invoke-RestMethod "$base/tasks/$($task.id)"
} while ($state.state -in @('queued','running'))
$state
Invoke-RestMethod "$base/tasks/$($task.id)/artifacts/workflow.json"
# 此时可重启第一个终端，确认任务仍为 awaiting_approval，然后批准。
Invoke-RestMethod "$base/tasks/$($task.id)/approval" -Method Post -ContentType application/json -Body '{"decision":"approve"}'
do {
    Start-Sleep -Milliseconds 500
    $state = Invoke-RestMethod "$base/tasks/$($task.id)"
} while ($state.state -in @('queued','running','cancelling'))
$state
Invoke-RestMethod "$base/tasks/$($task.id)/artifacts/report.json"
Invoke-RestMethod "$base/tasks/$($task.id)/artifacts/patch.diff"
```

完成后可下载 `context-selection.json`、`trace.jsonl`、`provenance.json`；SSE 在 `/tasks/{id}/events`。拒绝使用 `decision=reject`，取消使用 `POST /tasks/{id}/cancel`。等待期间不调用模型；执行中崩溃标记中断，不自动重放已开始的推理。

## 5. 使用真实模型

本地 `.env` 配置既有 `DEEPSEEK_API_KEY`，不把密钥放入请求正文。将 API 请求的 mode 改为 `live`，或：

```powershell
python -B -m repairflow run --bundle .tmp/repair-bundles/click-usage-empty --mode live --output .tmp/repair-demo/my-live-001
```

真实模式使用 DeepSeek `deepseek-flash` high thinking；最多两次调用、累计 60,000 Token、单次生成 32,768 Token（含思考）、65,536 上下文，源码最多五段/6,000 字符。保持截断停止规则。调用配置、实现哈希、证据及用量存入报告，云别名不等于冻结权重。

已有任务目录不会被 CLI 覆盖；API 任务使用独立 ID。外部源码始终不修改；通过的补丁也仍需人工审查，测试通过不保证完整语义正确。

## 6. 回归命令

```powershell
python -B -m pytest tests/test_repairflow.py tests/test_repairflow_service.py tests/test_service.py tests/test_service_persistence.py tests/test_workflow_approval.py tests/test_tentative_service.py -q -p no:cacheprovider
```

覆盖真实补丁应用、独立评分、错误候选回滚、哈希篡改拒绝、精确回放约束、服务 Worker、审批恢复、幂等、拒绝与取消等。集成验收与最新模型实验结果分别记录，避免把回放、工程检查和新模型成功数混在一起。

## 本轮已执行验收（2026-10-10）

- 相关回归 **137 passed**，Ruff 通过；没有重跑全仓库测试或 Docker 部署。
- `click-usage-empty` 真实任务离线 CLI/API 回放成功，补丁逐字节一致；审批重启恢复、真实 Worker、幂等、SSE、制品下载和拒绝无执行均通过。
- 新增测试还覆盖两轮反馈成功、错误公开候选回滚、公开通过但独立失败后的回滚、输入篡改拒绝、回放请求不匹配等。
- 一项真实 DeepSeek 集成验收通过：**1 次调用、15,725 Token**，独立 Target/Controls 通过。随后仅补充运行环境元数据，不改修复行为，真实运行的原实现哈希保留。
- 最终离线演示实现哈希审计通过。详情见 [验收摘要](unified-repair-flow-acceptance.json)。本轮未进行浏览器/TCP 端口验收；API 流程由 ASGI HTTP 客户端与真实子进程验收。
- 原完整任务池 **47/50** 不变，本次集成与历史回答回放不增加该分数。
