# 可选暂存发布服务 v1

新增 `tentative-approval-v1`，把已验证的任务级暂存 Worker 接入本地 FastAPI 队列、持久化审批和取消机制。默认修复流程和既有 LangGraph 工作流保持原行为。适配代码见 [service/tentative.py](../service/tentative.py)，真实模型效果继续使用上一轮 [发布对照](tentative-publication-v1.md)，本轮不新增修复率结果。

## 执行闭环

1. 客户端选择 `suite=certified`、`workflow=tentative-approval-v1`、`mode=live`，只能使用固定检索配置 `search_backend=off`。
2. 服务验证冻结实验、实现、任务模板、起始源码及公开检查哈希；缺少本地认证数据或数据被改动时返回 503，不排队。未知任务或配置不匹配返回 422。
3. 创建任务专属 `source/` 副本和持久化 `workflow.json`，到达 `awaiting_approval`，此时没有模型请求或源码修改。
4. 审批通过后执行原暂存 Worker，最多两次请求，共享 15,000 Token；第一轮及反馈只改独立暂存区，最终公开检查通过后才发布到该任务的 `source/`。
5. 服务成功要求 Worker 已提交、状态 completed 且最终公开检查通过。失败保留候选、生命周期和发布诊断；被拒绝的候选不出现在最终 `patch.diff` 中。

审批发生在模型执行前，不是逐补丁人工审批。发布到服务任务自己的副本，不写开发者的真实仓库或原认证快照。此路径的 `verification` 指认证公开检查，**不包含私有评分或完整上游测试**；API 状态 succeeded 也不能直接计入历史独立评分的修复率。

审批拒绝为 rejected；待审批取消为 cancelled，均不调用模型。推理时取消或超时停止进程树，原源码尚未发布。服务重启保留待审批状态；已经开始执行的任务使用独占创建的 execution-started 标记，阻止自动重放。外部修改待审批源码时停止执行并保留外部内容。

## 本地演示

当前注册两项已有认证任务：`click-usage-empty` 和 `itsdangerous-none-salt`。这不是任意 GitHub 仓库上传接口。注册依赖 D 盘工作区的历史 `.tmp/real-defects` 数据及评分 Python；仅 clone 源码无法立即运行这两项任务。目录显示 `requires_local_certification=true`，提交时检查实际可用性。

已有 8001 服务可以继续运行。需要试用新代码时，另开终端、进入项目根目录和 corecoder 环境，用独立端口与输出目录启动：

```powershell
$env:TEMP='D:\project_other\CoreCoder\.tmp\python-temp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
python -B -c "import uvicorn; from service.app import create_app; uvicorn.run(create_app(output='D:/project_other/CoreCoder/.tmp/tentative-service-demo'), host='127.0.0.1', port=8002)"
```

在另一个终端提交并查看审批计划：

```powershell
$repairJob = Invoke-RestMethod http://127.0.0.1:8002/tasks -Method Post -ContentType application/json -Body '{"suite":"certified","task_id":"click-usage-empty","mode":"live","workflow":"tentative-approval-v1"}'
Invoke-RestMethod "http://127.0.0.1:8002/tasks/$($repairJob.id)"
# 等状态到 awaiting_approval 后查看执行范围。
Invoke-RestMethod "http://127.0.0.1:8002/tasks/$($repairJob.id)/artifacts/workflow.json"
# approve 开始本地 Qwen 推理；reject 不执行模型。
Invoke-RestMethod "http://127.0.0.1:8002/tasks/$($repairJob.id)/approval" -Method Post -ContentType application/json -Body '{"decision":"approve"}'
Invoke-RestMethod "http://127.0.0.1:8002/tasks/$($repairJob.id)"
Invoke-RestMethod "http://127.0.0.1:8002/tasks/$($repairJob.id)/artifacts/lifecycle.json"
Invoke-RestMethod "http://127.0.0.1:8002/tasks/$($repairJob.id)/artifacts/transaction.json"
```

最后两项诊断在对应产物生成后可用，尚未生成时返回 404。`report.json` 和 `patch.diff` 仍通过原下载接口获取。源文件和完整候选保留在服务输出目录；不新增任意路径下载接口。SSE 仍只报告服务生命周期，不是实时模型 Token 流。

## 验证与边界

新测试使用子进程中的模拟 LLM 回答，真实执行片段编辑、Python 编译、导入、公开用例和最终发布，验证 API 审批与持久化。另通过 ASGI/TestClient 和真实服务 Worker 对两项实际认证快照执行“提交 → 待审批 → 拒绝”，两项均保持起始文件字节，0 次模型和私有评分请求。本轮没有启动 TCP 演示服务器，也没有批准后的新模型执行；此前真实修复对照仍是冻结 Worker 级结果。

新增专项 **16 passed（19.71 秒）**，最终 Windows 全量 **1,134 passed、2 skipped（188.77 秒）**，Ruff 通过。

机器验收摘要见 [JSON](tentative-service-v1.json)。测试入口为 [test_tentative_service.py](../tests/test_tentative_service.py)。

本路径要求服务独占任务工作区。最终多文件写入没有崩溃安全原子性，强制终止恰好发生在发布写入窗口时可能留下部分修改；不能宣称所有取消都保持起始源码。未提供操作系统沙箱、跨进程发布锁或生产鉴权；本轮不部署到云端、不重启现有服务，也不运行容器验收。

下一步优先解除服务对历史绝对路径和临时产物的依赖：生成可校验、只包含起始源码与公开契约的独立任务包，再验证批准后的真实 HTTP 执行。这比继续追加 none-salt 提示词实验更接近可复现交付。
