# 真实 HTTP 服务故障验收

## 为什么增加这一轮

原持久化测试主要通过 TestClient、预置数据库记录和孤儿进程验证恢复逻辑；Docker 验收仍受本机引擎启动故障阻塞。本轮直接运行真实 Uvicorn 子进程和 HTTP Client，实际结束服务进程，再启动新服务，检查数据库、Worker、事件和幂等请求之间的完整链路。

新增 `deploy/local_acceptance.py` / `deploy/local_server.py`。复用现有 HTTP 验收 Client；生产服务、`corecoder/`、`evals/`、预算及评分协议没有修改。Docker validation 阶段也已纳入这项测试，待引擎恢复后在 Linux 内执行。

## 实际结果

本机 Windows 真实 CLI 验收 **status=passed，22 项检查全部通过**，记录位于 `.tmp/local-http-acceptance-v1/acceptance.json`。每次服务启动的 PID、命令、退出状态、是否强制终止，以及 stdout/stderr 日志均保留。工作数据和 SQLite 在同目录 `data/`。

| 场景 | 已确认的行为 |
| --- | --- |
| 实际 scripted 修复 | 现有独立验证器评分通过；unchanged 评分失败，补丁可下载 |
| 正常重启 | 原任务状态、补丁、SSE 和幂等键仍可查询；相同请求返回原 ID |
| 运行取消 | 长任务确实创建 Worker 及子进程后才取消；任务 cancelled，两个进程均退出 |
| 服务强制终止 | 仅结束验收服务进程；确认 Worker 和子进程仍存活，形成真实孤儿现场 |
| 中断恢复 | 新服务清理旧 Worker/子进程，任务 interrupted，同键重发不重跑，没有生成新的 result.json |
| 排队恢复 | 崩溃前任务确实 queued；新服务恢复执行，同键保持原 ID，后续重启没有重复生命周期事件 |
| 正常退出 | 在 Worker/子进程均运行时触发正常停止；lifespan 取消、清理进程树，重启后仍为 cancelled |
| 收尾 | 结束本轮服务，检查所有已记录 Worker/子进程退出；保留任务数据及日志 |

scripted 部分运行真实修复/独立验证链路；长任务、排队和故障部分使用 `tests.service_worker_stub`。Stub 的 succeeded 只验证调度和恢复，不计模型修复成功率。本轮没有真实模型调用，也没有新增检索收益结论。

## 复跑

在项目根目录、已安装 service extra 的 corecoder 环境执行：

```powershell
python -m deploy.local_acceptance
```

默认创建 `.tmp/local-http-acceptance/{随机ID}`，自动选择回环空闲端口。显式输出目录必须没有 `data/`，拒绝复用已有任务现场，避免历史幂等记录掩盖新的执行。需要指定目录时使用全新的名字：

```powershell
python -m deploy.local_acceptance --output .tmp/local-http-acceptance-my-run
python -m pytest tests/test_local_deploy_acceptance.py -q
```

验收辅助服务仅绑定 127.0.0.1；测试专用 `/__acceptance__/shutdown` 请求用于跨平台触发 Uvicorn 正常退出。该端点仅注册在显式启动的辅助服务中，**未添加到生产 service.app**，runtime 镜像也没有复制该辅助模块。强制停止只针对验收器自身创建的 Popen 服务进程；清理 Worker 前核对 PID 和创建时间，避免误操作复用 PID。

当前已有 8001 服务及 `.tmp/service` 没有被访问、停止或修改。CLI 和 pytest 均使用独立目录/端口；退出后产物保留，端口释放。该脚本从仓库 checkout 运行。

## 验收边界与下一步

本文首轮验证的是 **Windows 主机真实 HTTP/进程故障恢复**。后续 2026-10-07 已将相同回归纳入 Linux 容器测试，48 项专项及容器端到端检查均通过，见 [容器部署文档](container-deployment-v1.md)。断电、磁盘损坏、多 Worker 或分布式恢复仍未验证。

真实 CLI 的 22 项检查已通过，新增自动回归覆盖完整 HTTP 故障路径、收尾释放端口及拒绝复用任务目录。全量回归 **841 passed、2 skipped（103.02 秒）**，Ruff 与 Git diff 空白检查通过。CLI 验收的五次服务启动均已退出，其中一次为预期的强制结束；所有已记录 Worker/子进程清理确认通过。

服务闭环已有主机及 Linux 容器故障证据；容器链路可通过 `python -m deploy.acceptance` 独立复跑。不需要继续扩充人工检索任务来验证这些工程行为。
