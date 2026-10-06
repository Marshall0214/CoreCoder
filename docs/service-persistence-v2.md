# 本地服务持久化与恢复

## 本轮解决的问题

在 FastAPI MVP 上补齐任务持久化、幂等提交、重启恢复和有界历史。服务停止后，已完成任务仍可查询、下载产物和续读 SSE；客户端重发同一个请求不会再次启动模型任务。实现位于独立 `service/`，没有修改冻结的 `corecoder/`、`evals/` 或实验评分协议。

| 情况 | 处理 |
| --- | --- |
| 相同 Idempotency-Key、相同规范化请求 | 返回原任务 ID，排队满时也能重放 |
| 相同键、不同请求内容 | HTTP 409 |
| 原任务已超过历史保留范围，同键同请求 | HTTP 410，不创建新任务 |
| 重启时 queued | 恢复排队执行 |
| 重启时 running / cancelling | 清理可确认身份的旧进程树，标记 interrupted，不自动重试 |
| 已完成任务 | 保留原状态和结果，不执行 Worker |

未提供幂等键的提交仍然创建新任务。键限 1–128 个字母、数字或 `._:-`；请求经 Pydantic 填充默认值后计算 SHA-256，因此省略默认字段与显式填写默认值等价。`interrupted` 表示运行被服务中断，不能算作修复成功，也不等同于已证明模型修复失败；确需重新执行时，用新键明确创建新任务。

## 存储与进程恢复

默认数据目录仍为 `.tmp/service/`。`tasks.sqlite3` 使用 SQLite WAL；任务状态及对应 SSE 事件在同一事务提交，初次任务记录和幂等键也原子提交。`tasks` 保存请求、结果和进程身份；`events` 保存递增事件；`idempotency` 保存请求指纹及原任务 ID。每个 UUID 目录仍保留请求、日志、独立验证和补丁。

启动器在执行 Worker 前等待 `start-approved`。服务先将 PID 和进程创建时间持久化，再写启动确认；未经确认的进程最多等待 10 秒，随后退出，不调用模型。启动器另外原子写入 `worker-identity.json`，供服务在 PID 尚未写库的崩溃窗口识别旧进程。恢复时同时核对 PID、创建时间和命令行中的绝对 job.json 路径，避免误杀复用 PID 的其他进程。

身份无法确认的进程不强制终止；进程权限错误或确认后的清理失败会阻止服务正常启动。这里提供本机进程管理，不是容器沙箱。运行任务即使已有 result.json，重启后仍保守标记 interrupted；不从不确定的执行阶段继续，更不自动再次产生模型费用。

同一个数据目录只允许一个服务进程持有 `.owner.lock`，禁止多 Uvicorn Worker 共享该目录。OS 在进程退出时释放锁；不要删除锁文件来绕过互斥。原内存版服务没有保存数据库，无法从它的旧产物自动恢复任务记录。

默认保留最近创建的 **100 个终态任务**，排队/运行任务不参与淘汰。淘汰同时删除数据库任务和事件，内存记录也删除；对应 API 返回 404。**幂等键墓碑和磁盘产物暂不自动删除**，以避免旧键重发触发重复执行，并保留实验材料。因此当前只限制终态查询历史，不宣称总磁盘占用或幂等键数量有界；后续需要独立的归档与清理策略。

## 本机验证

当前已有服务可以继续运行；本轮没有重启或停止它。待原任务完成后，手动退出原服务并在项目根目录重启即可使用新代码：

```powershell
conda activate corecoder
python -m uvicorn service.app:create_app --factory --host 127.0.0.1 --port 8001
```

在另一个 PowerShell 终端提交两次，两个响应应具有相同 ID：

```powershell
$repairHeaders = @{ 'Idempotency-Key' = 'demo-persistence-001' }
$repairBody = '{"task_id":"timeout-units","mode":"scripted"}'
$first = Invoke-RestMethod http://127.0.0.1:8001/tasks -Method Post -Headers $repairHeaders -ContentType application/json -Body $repairBody
$second = Invoke-RestMethod http://127.0.0.1:8001/tasks -Method Post -Headers $repairHeaders -ContentType application/json -Body $repairBody
$first.id -eq $second.id
Invoke-RestMethod "http://127.0.0.1:8001/tasks/$($first.id)"
```

等待 succeeded 后正常退出并再次启动服务，重新查询该 ID，应仍是 succeeded；同键提交仍返回原 ID。不同参数复用同键应返回 409。Swagger 页面 `/docs` 的 POST /tasks 也可填写可选 `idempotency-key` 请求头。

自动验收使用独立临时目录，不访问正在运行的 `.tmp/service`，也不调用真实模型：

```powershell
python -m pytest tests/test_service.py tests/test_service_persistence.py -q
python -m pytest tests -q
python -m ruff check service tests/test_service.py tests/test_service_persistence.py tests/service_worker_stub.py
```

专项 **21 passed**，覆盖既有服务行为以及真实 scripted 任务重启后的状态/产物/SSE、并发幂等提交、冲突、队列满重放、排队恢复一次、两种运行状态中断、历史淘汰与墓碑、目录所有权、匹配/不匹配 PID 清理、未经确认的启动器及恢复清理。孤儿进程测试使用真实子进程和模拟持久化现场；没有把它表述为断电或磁盘损坏验收。全量回归 **821 passed、1 skipped（85.65 秒）**，Ruff 与 Git diff 空白检查通过。本轮没有新增真实模型调用。

## 下一步与简历边界

现在可以写：FastAPI/Pydantic 任务接口、异步有界调度、独立 Worker、SQLite 事务持久化、请求幂等、SSE 重放、取消和重启中断恢复。SQLite 是本机交付方案，不能写成 PostgreSQL/Redis 或分布式队列经验；多进程协调、权限、Docker/Linux 部署仍未验收。

下一步优先接入代码知识 MCP Server，复用已验证的检索能力，提供标准化调用和互操作测试。PostgreSQL/Redis、工作流和部署按后续独立交付推进，不继续扩充当前检索实验批次。
