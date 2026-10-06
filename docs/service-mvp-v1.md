# FastAPI 本地修复服务 MVP

本文记录首版 MVP 的实现与验收。当前已增加持久化、幂等提交和重启恢复，见 [本地服务持久化与恢复](service-persistence-v2.md)；下文内存状态限制仅描述首版。

## 交付

新增独立 `service/` 适配层，接入既有 `evals.runner.run_task`；corecoder/evals 源码及已有实验策略未修改。现在可以从 HTTP 提交任务、查询状态、订阅 SSE 生命周期事件、取消执行，并下载补丁和独立验证报告。

| 接口 | 用途 |
| --- | --- |
| GET /health | 服务健康 |
| GET /catalog | 两套可信人工任务目录 |
| POST /tasks | Pydantic 校验后提交，返回 202 和任务 ID |
| GET /tasks/{id} | 状态、独立评分和 Token 指标 |
| GET /tasks/{id}/events | SSE 生命周期事件，支持 Last-Event-ID 续读 |
| POST /tasks/{id}/cancel | 幂等取消，终态不改变 |
| GET /tasks/{id}/artifacts/patch.diff | 补丁下载 |
| GET /tasks/{id}/artifacts/report.json | 完整评测报告下载 |

状态为 queued → running → succeeded/failed；取消经过 cancelling → cancelled，排队任务可直接 cancelled，超时为 timed_out。API 成功须同时满足报告 accepted、status=passed 和独立 verification.passed，Worker 自称完成不能计分。SSE 为生命周期事件，不是模型 Token 流或实时 Agent Trace。

每个任务一个 UUID 目录、一个独立服务 Worker；已有评测器再创建干净候选工作区并独立评分。默认并发 1、最多 16 个未完成任务、外层墙钟上限 240 秒。内层执行预算为 15000 Token、Worker 180 秒、验证 15 秒。默认真实模型为本地 Ollama qwen3.5:27b，temperature=0、reasoning=none，输出 2048 Token、窗口 16000。

运行中的取消和超时通过进程树停止，并等待清理完成；psutil 补充处理拥有独立进程组的后代。退出 lifespan 时取消并等待未完成任务。排队取消不会启动 Worker，取消保留工作目录和已有日志。FastAPI lifespan、StreamingResponse 与测试方式参考[官方测试文档](https://fastapi.tiangolo.com/advanced/testing-events/)及[流式响应文档](https://fastapi.tiangolo.com/advanced/stream-data/)；后代进程枚举使用 [psutil 官方 API](https://psutil.io/)。

## 本机启动与演示

在项目根目录、corecoder conda 环境运行：

```powershell
python -m pip install -e ".[service]"
python -m service
```

监听 `127.0.0.1:8000`，OpenAPI 演示页为 `http://127.0.0.1:8000/docs`。当前从仓库 checkout 运行；原 CoreCoder wheel 打包范围未扩展，不宣称已发布包含服务和评测 fixture 的分发包。

另开终端：

```powershell
# scripted 为已知参考补丁驱动的离线验证演示，不计模型修复能力。
$repairTask = Invoke-RestMethod http://127.0.0.1:8000/tasks -Method Post -ContentType application/json -Body '{"task_id":"timeout-units","mode":"scripted"}'
Invoke-RestMethod "http://127.0.0.1:8000/tasks/$($repairTask.id)"
curl.exe -N "http://127.0.0.1:8000/tasks/$($repairTask.id)/events"
Invoke-WebRequest "http://127.0.0.1:8000/tasks/$($repairTask.id)/artifacts/patch.diff" -OutFile .tmp/service-demo.patch

# Ollama 已运行时提交真实模型任务。
$repairLive = Invoke-RestMethod http://127.0.0.1:8000/tasks -Method Post -ContentType application/json -Body '{"task_id":"timeout-units","mode":"live","search_backend":"keyword"}'
Invoke-RestMethod "http://127.0.0.1:8000/tasks/$($repairLive.id)"
# 运行中需要取消时执行；已结束任务保持原状态。
Invoke-RestMethod "http://127.0.0.1:8000/tasks/$($repairLive.id)/cancel" -Method Post
```

任务体可选 suite=smoke/localization，mode=scripted/unchanged/reference/live，search_backend=off/none/keyword。不接受客户端提供文件系统路径、模型地址或任意命令。原始产物在 `.tmp/service/{任务ID}`：job、服务 Worker 日志、result，以及 runs 下原有 Trace、工作区、补丁和验证日志。状态查询的结果仅摘要，完整报告可下载。断线不会取消任务，可重新查询或用 SSE 事件 ID 续读。

## 已执行的验收

9 项服务测试覆盖：真实 scripted 修复及 unchanged 失败、两个并行任务/工作区隔离、补丁/报告下载、SSE 回放、输入拒绝与未知 ID、容量限制、排队与运行取消、后代进程退出、超时、Worker 崩溃、伪成功拒绝和 lifespan 关闭清理。测试不调用真实模型，使用真实子进程及现有独立验证器。

另启动真实 Uvicorn HTTP 服务进行三项 timeout-units 验收：scripted succeeded、unchanged failed、**Ollama live succeeded**。live 有 **4 次 LLM 调用、9016 Prompt Token、495 Completion Token，总计 9511 Token**，补丁只修改 transport.py，Target 和 Controls 各两项全部通过。该 live 运行采用已有 Agent 工具循环，不是此前函数实验的单次补丁协议，两者不能混合比较。

HTTP 验收记录在 `.tmp/service-acceptance/http-acceptance.json`，包含三项终态、SSE 和补丁；服务日志也保留。验收服务已停止，没有遗留监听进程。本机已安装并验证 FastAPI 0.142.2、Uvicorn 0.54.0、HTTPX 0.28.1、psutil 7.2.2；原隔离缺陷检查环境未安装这些依赖。

```powershell
python -m pytest tests/test_service.py -q
python -m pytest tests -q
python -m ruff check service tests/test_service.py tests/service_worker_stub.py
```

服务依赖为可选 extra；未安装时服务测试跳过，完整验收须安装 service extra。服务测试 **9 passed**，最终全量 **809 passed、1 skipped（81.52 秒）**；新增代码 Ruff 和 Git diff 空白检查通过。

## 范围与下一步

这是本机可信人工任务 MVP，不接受任意外部仓库，也没有把历史 Click/ItsDangerous 实验直接注册成 API 任务。状态、队列及 SSE 事件保存在内存，重启后无法查询或恢复；完成任务暂未做保留数量上限，磁盘产物需管理。仅本地回环监听，没有鉴权、多用户权限、容器沙箱、资源配额或生产负载验收；本轮只在 Windows 验证进程树行为，Linux 验收留给部署阶段。

下一步优先实现持久化任务状态、幂等提交、重启恢复和有界历史保留，再接入 PostgreSQL/Redis、工作流及 MCP Server。LangGraph、Docker/Linux 和云部署仍是计划，不能计为已实现的简历能力。已有 API、Pydantic 契约、异步调度、独立 Worker、取消与独立验证现在可以写入个人贡献。
