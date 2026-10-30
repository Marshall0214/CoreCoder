# Langfuse 学习：运行检查与故障演练

本轮目的是理解“服务启动”和“数据可用”的区别。使用已有合成 Issue、脚本响应和 Docker 公开检查，未调用模型或付费 API；所有新增文件在 D 盘。演练只操作 `corecoder-langfuse` 的 Web、Worker，未操作已有 8001 服务。

## 1. 六个组件各自负责什么

| 组件 | 主要职责 | 排查时看什么 |
| --- | --- | --- |
| Web | 网页、认证和接收追踪请求 | HTTP、就绪状态、数据库检查、项目密钥认证 |
| Worker | 后台处理接收的事件 | 容器是否暂停、内部健康接口、新 Trace 能否完整出现 |
| PostgreSQL | 用户、项目等事务数据 | 数据库容器健康、Web 数据库检查 |
| ClickHouse | 观测及评分的分析存储 | 容器健康，以及实际数据回读 |
| Redis | 队列及缓存 | 容器健康；本轮未增加队列长度采集 |
| MinIO | 本地对象存储 | 容器健康；单独健康不能证明端到端入库 |

职责依据[官方自托管架构](https://langfuse.com/self-hosting)。本轮通过暂停 Worker 验证其对当前数据可见性的影响，没有逐条检查 Redis/S3 内部事件或验证所有故障组合。

## 2. 先分清四层证据

1. **存活：**Web `/api/public/health` 能响应。
2. **就绪及依赖：**`/api/public/ready`、带 `failIfDatabaseUnavailable=true` 的 health、六个容器状态，以及 Worker 内部健康接口。
3. **有权限读取：**项目 API 使用当前项目密钥认证成功。旧 Trace 可读仅说明旧数据仍可访问。
4. **本次入库：**新任务的服务器节点数量与本地操作一致、节点完整结束、父子关系正确且三项评分可回读。

健康接口的含义见[官方说明](https://langfuse.com/self-hosting/configuration/health-readiness-endpoints)。默认 health 不检查数据库，所以脚本同时检查带数据库参数的版本；Web 就绪也不能替代 Worker 和新数据回读。

当前 4.69.0 镜像在容器地址监听：Web 使用 `web:3000`，Worker 使用 `worker:3030`。本机实测容器内 loopback 请求失败，不能直接照抄其他部署的 localhost 探针。Worker 3030 不发布到宿主机。

## 3. 两项实际演练及结果

| 故障 | 修复任务 | Langfuse 现象 | 恢复结果 |
| --- | --- | --- | --- |
| 停止 Web | 公开检查通过，保留非空补丁和本地 Trace；`accepted=false` | 观测标记 `unavailable`，错误类型 `ConnectTimeout` | 启动 Web 后所有运行检查恢复正常 |
| 暂停 Worker，保持 Web 在线 | 公开检查通过，仍保留本地证据 | Web 的 HTTP、就绪、数据库及项目认证检查均通过；任务为 `submitted_unconfirmed`，9 次回读从 0.06 到 16.36 秒均为 0 节点、0 评分 | 取消暂停后约 2.09 秒回读到 7 个节点、3 项评分，数量、父子关系、结束状态及摘要白名单通过验证 |

服务器演练 Trace：[查看执行树](http://127.0.0.1:3300/project/corecoder-issues/traces/d7c51ad49dc9f0586d36fceac5897d2e)。7 个节点包括根任务、两次脚本响应、符号读取、补丁应用、两次 Docker 检查。脚本响应不是模型推理。

**学习重点：**修复执行和追踪上传是两条链。追踪服务故障不能把已通过公开检查的任务改判失败；SDK flush 返回也不能证明后台已完成入库。本轮恢复后的延迟是单次观察值，不是延迟 SLA，也不证明无限积压或断电后的零丢失。

本地完整 Trace 是故障时的保底证据；**当前没有离线自动补传功能**。Web 停止期间这次任务没有生成服务器 Trace，恢复 Web 不会自动把该任务的本地文件补入 Langfuse。Worker 暂停的恢复则验证了本次已提交事件随后可见，二者不同。

## 4. 可复现操作

沿用[部署文档](langfuse-local.md)中的 D 盘依赖、PYTHONPATH、TEMP 和本地凭据。以下检查不调用模型，输出路径必须是新路径：

```powershell
python -B -m deploy.langfuse.doctor --env-file .tmp/langfuse-local/.env --output .tmp/langfuse-doctor-002.json --trace-id d7c51ad49dc9f0586d36fceac5897d2e
```

`healthy` 代表本次运行探针通过；`degraded` 返回退出码 1。`historical_readback` 单列，不参与健康判断，也不宣称证明新数据入库。脚本只输出选定状态、HTTP 状态码和异常类型，不输出容器环境、密码、HTTP 响应正文或原始错误日志。

如需重现故障，先确认可暂时中断本项目的 Langfuse 网页和后台处理，再运行：

```powershell
python -B -m deploy.langfuse.drill --entry .tmp/issue-mvp-starter-20261029/catalog/sample --env-file .tmp/langfuse-local/.env --output .tmp/langfuse-operations-002
```

该命令要求六个服务初始正常、已有可信合成任务及本地沙箱镜像。固定 Compose 项目名，停止 Web 或暂停 Worker；用 `finally` 尝试恢复，不删除卷、不拉镜像。暂停状态下跳过 Worker 的容器内探针，避免 exec 阻塞。主机断电、强杀进程或 Docker 恢复命令本身失败仍可能需要人工恢复：

```powershell
docker compose --project-name corecoder-langfuse --env-file .tmp/langfuse-local/.env -f deploy/langfuse/compose.yaml unpause worker
docker compose --project-name corecoder-langfuse --env-file .tmp/langfuse-local/.env -f deploy/langfuse/compose.yaml up -d --pull never web worker
```

不使用 `down -v`、`prune` 或其他项目的停止命令。

## 5. 验收与下一课

本轮新增 10 项测试，覆盖 Web 正常但 Worker 暂停、数据库检查失败、认证失败、旧记录缺失、Docker/HTTP 不可用、错误脱敏、项目名固定及故障后恢复。与既有追踪、用量、回读检查合计 **49 项通过**，Ruff 通过。实际两项演练通过，最终六个服务及 11 项运行检查正常。

冻结证据在 [清单](langfuse-operations-20261030.json) 和 `langfuse_operations_20261030/`，共 15 份文件，包含诊断、演练摘要和对应脚本/测试快照；不包含凭据、任务仓库原始源码或原始执行日志。新模型调用 **0**，不新增修复率成绩。

下一课优先学习**备份与隔离恢复**：先区分 PostgreSQL、ClickHouse 和对象存储中的数据，再设计恢复到独立目录/实例的演练。此轮尚未实施备份、自动告警、离线补传或 Langfuse 数据集实验。
