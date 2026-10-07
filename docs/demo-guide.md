# 5 分钟工程演示

目标：展示任务计划、人工审批、跨重启恢复、独立验证和防重复执行。使用 `timeout-units` 人工任务：追踪配置秒数到请求毫秒数，保留零、小数和默认行为。

**本次用 scripted 模式：候选补丁由确定性的离线工具流程生成，不是现场 LLM 修复。**它用于稳定演示工程链路。真实模型检索/修复实验单独展示 [结果报告](second-repo-repair-v1.md)，不混作现场结果。

## 演示前准备

从仓库 checkout、已有 corecoder 环境运行，需要 service/workflow extra。当前机器的 SQLite 扩展在 D 盘 `.tmp/workflow-deps`；若该目录不存在，先在 D 盘环境安装所需依赖，参考 [审批说明](workflow-approval-v1.md)，不要自动往 C 盘现有环境追加包。

终端 A：

```powershell
Set-Location D:\project_other\CoreCoder
$env:PYTHONPATH = 'D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp\python-temp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$demoData = Join-Path (Get-Location) ('.tmp/demo-' + [guid]::NewGuid().ToString('N'))
# 8003 需空闲；若已使用，换一个端口，并同步终端 B 的 $base。
python -B -m deploy.local_server --data $demoData --port 8003
```

`deploy.local_server` 是既有验收辅助入口，调用同一个生产 create_app，但附带私有 shutdown 接口；仅在 loopback 演示，不作为公开部署命令。它使用独立新目录，不争用现有 8001 服务或默认任务数据库。生产部署入口见 [容器说明](container-deployment-v1.md)。

终端 B：

```powershell
$base = 'http://127.0.0.1:8003'
$demoKey = 'demo-' + [guid]::NewGuid().ToString('N')
function Wait-DemoTask($id, $states) {
    $deadline = (Get-Date).AddSeconds(60)
    do {
        $row = Invoke-RestMethod "$base/tasks/$id"
        if ($states -contains $row.state) { return $row }
        if (@('failed','cancelled','timed_out','interrupted','rejected') -contains $row.state) {
            throw "Unexpected terminal state: $($row.state)"
        }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)
    throw 'Task did not reach the expected state; inspect its report and worker logs.'
}
Invoke-RestMethod "$base/health"
```

## 0:00–1:00：提交任务并看计划

```powershell
$body = '{"task_id":"timeout-units","mode":"scripted","workflow":"langgraph-approval-v1"}'
$task = Invoke-RestMethod "$base/tasks" -Method Post -Headers @{ 'Idempotency-Key' = $demoKey } -ContentType application/json -Body $body
$waiting = Wait-DemoTask $task.id @('awaiting_approval')
$waiting | Select-Object id,state,approval,result
$snapshot = Invoke-RestMethod "$base/tasks/$($task.id)/artifacts/workflow.json"
$snapshot.plan | ConvertTo-Json -Depth 5
```

预期：awaiting_approval，approval/result 为 null。计划列出 settings.py、transport.py、service.py、15000 Token 上限及一次尝试。计划由代码生成，尚未执行修复；可在终端 A 的数据目录确认无 runs 目录。

## 1:00–2:00：重启，确认审批状态仍在

只在终端 A 按 Ctrl+C，退出自己刚启动的演示进程；然后使用**同一个** `$demoData` 重启：

```powershell
python -B -m deploy.local_server --data $demoData --port 8003
```

终端 B 再查询：

```powershell
Invoke-RestMethod "$base/tasks/$($task.id)" | Select-Object id,state,approval
$replayed = Invoke-RestMethod "$base/tasks" -Method Post -Headers @{ 'Idempotency-Key' = $demoKey } -ContentType application/json -Body $body
$replayed.id -eq $task.id
```

预期：仍 awaiting_approval；重复提交返回同一 ID。这里演示正常重启；强制退出/孤儿清理由 [真实 HTTP 验收记录](workflow-approval-acceptance-v1.json)佐证，不在现场随机结束其他进程。

## 2:00–3:30：批准，检查独立验证与补丁

```powershell
Invoke-RestMethod "$base/tasks/$($task.id)/approval" -Method Post -ContentType application/json -Body '{"decision":"approve"}'
$done = Wait-DemoTask $task.id @('succeeded')
$done.result | ConvertTo-Json -Depth 8
(Invoke-WebRequest "$base/tasks/$($task.id)/artifacts/patch.diff" -UseBasicParsing).Content
$report = Invoke-RestMethod "$base/tasks/$($task.id)/artifacts/report.json"
$report | Select-Object status,accepted,verification | ConvertTo-Json -Depth 8
```

预期：status=passed、accepted=true、verification.passed=true。解释：批准只允许执行，真正 succeeded 取决于独立验证；这里不展示虚构的 LLM Token 消耗。

## 3:30–4:15：重复批准与事件记录

```powershell
$again = Invoke-RestMethod "$base/tasks/$($task.id)/approval" -Method Post -ContentType application/json -Body '{"decision":"approve"}'
$again.id -eq $task.id
$again.updated_at -eq $done.updated_at
(Invoke-WebRequest "$base/tasks/$($task.id)/events" -UseBasicParsing).Content
```

预期：同一任务和终态时间，事件顺序为 queued → running → awaiting_approval → queued → running → succeeded。终态 SSE 会结束；等待时 SSE 会保持连接，不在待审批阶段用该命令阻塞演示。需要时在终端 A 的 `$demoData/<id>/runs` 确认只有一次执行目录。

## 4:15–5:00：拒绝，不产生修复

```powershell
$rejectedTask = Invoke-RestMethod "$base/tasks" -Method Post -ContentType application/json -Body $body
Wait-DemoTask $rejectedTask.id @('awaiting_approval') | Out-Null
Invoke-RestMethod "$base/tasks/$($rejectedTask.id)/approval" -Method Post -ContentType application/json -Body '{"decision":"reject"}'
$rejected = Wait-DemoTask $rejectedTask.id @('rejected')
$rejected | Select-Object id,state,approval,result
```

预期：rejected / approval_rejected，无 runs 或 execution-started。可选取消演示：再新建一个待审批任务，用 `POST /tasks/{id}/cancel`，预期 cancelled；取消和拒绝区别是生命周期控制与审批决定。

演示结束，在终端 A 按 Ctrl+C，仅退出自建进程。保留 D 盘新建演示目录供复查，不删除原服务、原任务卷或实验产物。

## 可选 MCP 展示（另加 30 秒）

项目根目录、同一环境执行：

```powershell
python -B -m mcp_servers.demo --workspace evals/fixtures/timeout-units/workspace --query timeout
```

它启动真实 stdio Server，列出 search_code/list_code_files/read_code，搜索后按哈希读取代码，再关闭 Server；不调用模型，不修改源码。这是独立 MCP 互操作演示，不意味着上面的 API 修复自动使用 MCP。

## 如何讲实验结果

打开 [总览的结果表](project-overview.md)：Click 有局部差异，第二仓库没有复现；Dense 召回较高却没有稳定修复收益。说明控制变量、独立评分、失败保留和样本边界，再回答为何不直接宣传成功率提升。完整复跑需要冻结快照和本地模型，不属于这个离线 5 分钟演示。

再用 [求职证据索引](portfolio-evidence.md)选一个近期失败案例：Qwen / DeepSeek 六项均 5/6；加入源码契约证据仍均 5/6，并产生 Controls 回归。展示补丁能编译却不能正确签名的区别，以及更少 Token 为什么只是失败提前停止。该段使用冻结报告，不启动真实模型或读取 API Key。

## 历史交付检查

2026-10-07：README 行数约束测试 1 passed；54 个本地文档链接有效；本文 9 段 PowerShell 示例通过语法解析。使用既有 `deploy.approval_acceptance` 复跑真实 HTTP 审批链路，18 项检查全部通过，自建服务及跟踪 Worker 已清理，记录 `.tmp/delivery-demo-acceptance-v1/acceptance.json`。

MCP 演示成功发现三个工具并完成搜索与哈希读取，输出 `.tmp/delivery-mcp-demo.json`。本轮仅整理文档，不重新运行全量回归、容器构建或真实模型实验；864/71 等工程数字引用上一轮版本化验收。以上自动验收与语法检查不等于已经完成用户的手动讲解或录屏。

## 求职交付核查 v2

更新简历、证据索引和近期失败说明后，重新检查当前文档链接、PowerShell 示例、README 约束，并执行只读 MCP 演示；结果见 [交付摘要](portfolio-delivery-v2.json)。最新全量 1,023 passed、2 skipped 引用已有契约对照验收，本轮不重跑模型、全量测试、服务或容器。用户手动演讲、录屏与公开提交仍待完成。
