# 本地 Langfuse：接入与部署

本阶段只增加可观测性，不改变修复策略，不调用付费 API 或 LLM 裁判。Langfuse 是可选依赖，默认关闭；本地 `trace.jsonl` 仍是完整执行记录。

**当前状态：本地服务已上线并完成服务器回读验收。**CLI/API 合成演示各留存一条 Trace，共 14 个节点；登录、评分与整套服务重启后记录保留均已验证。模型调用为零，准确率实验未变。[服务验收](langfuse-server-20261029.md)；[上一阶段离线验收](langfuse-20261029.md)保留原始网络故障记录。

## 能看到什么

| 节点/记录 | 内容 | 边界 |
| --- | --- | --- |
| issue-repair | 仓库、基线版本、输入哈希、模式、最终状态与指标 | 一次执行对应一个根节点；不代表独立验收 |
| model-call / scripted-response | 模型、调用耗时、已知 Token 用量、错误状态 | 脚本响应不是模型推理；未知用量保留为空 |
| 工具节点 | 读取/修改路径与符号、状态、哈希、错误码 | 不上传源码、Prompt、替换锚点或原始测试日志 |
| docker-public-checks | 检查阶段、通过/失败/跳过数与耗时 | 公开开发检查，不是独立评分 |
| budget-stop | 预算停止原因 | 预算由执行器控制 |
| 确定性评分 | public_checks_passed、fresh_model_calls、independent_verification_available | 后者在当前 prepared-Issue 流程恒为 false；无 LLM 评分 |

SDK 不可用、配置错误或服务离线，只影响观测状态，不改变补丁、测试、审批或回滚结论。允许的服务地址仅为本机回环地址，避免误发云端。

## 1. 准备环境与凭据

在仓库根目录，激活 `corecoder`（Python 3.11+）。依赖、缓存、凭据与任务输出均放 D 盘：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
python -m pip install --target .tmp/langfuse-deps --no-cache-dir --no-compile 'langfuse==5.0.4'
$env:PYTHONPATH='D:\project_other\CoreCoder\.tmp\langfuse-deps;D:\project_other\CoreCoder\.tmp\workflow-deps;D:\project_other\CoreCoder'
python -B deploy/langfuse/prepare.py --output .tmp/langfuse-local
```

本机已执行上述准备，不要重复覆盖 `.tmp/langfuse-local`。脚本要求新目录，随机生成项目密钥、数据库密码与本地账号；登录信息只在 `.tmp/langfuse-local/login.txt`，不要提交或发送到聊天。SDK 只读取所选文件中的三个 `LANGFUSE_*` 连接字段，不把数据库/登录/模型凭据装入进程环境。

Windows 下脚本会检查 Docker Desktop 数据目录是否在 D 盘。本机已确认位于 `D:\Users\admin\AppData\Local\Docker\wsl\DockerDesktopWSL`；命名卷保存在该 Docker 磁盘内部。后续迁移或重装 Docker 需要重新核对，不能只凭工作目录在 D 盘判断。

## 2. 启动独立服务

```powershell
docker compose --env-file .tmp/langfuse-local/.env -f deploy/langfuse/compose.yaml config --quiet
docker compose --env-file .tmp/langfuse-local/.env -f deploy/langfuse/compose.yaml up -d --pull never
docker compose --env-file .tmp/langfuse-local/.env -f deploy/langfuse/compose.yaml ps
Invoke-RestMethod http://127.0.0.1:3300/api/public/health
```

本机所需镜像已导入，可直接使用 `--pull never` 启动；新机器需先执行相同参数的 `pull`，或导入经过完整性校验的官方镜像。

服务地址 `http://127.0.0.1:3300`，对象存储端口 **13390**；均只监听回环地址，不占用已有 8001 服务。原 3390 位于本机 Windows 保留端口范围，已只修改 `.tmp/langfuse-local/.env` 的 `MINIO_PORT`，凭据未重建。新准备脚本默认也使用 13390。数据库等不发布宿主机端口。

Web 健康检查通过容器 DNS `web:3000` 请求健康接口，Worker 等待 Web 健康再启动，避免首次数据库迁移竞争。当前镜像在容器地址提供服务，不能把容器内 `127.0.0.1:3000` 可达当作默认前提。容器有内存、CPU 与日志大小约束；本地栈不是多租户生产部署。

Compose 使用 Langfuse 4.69.0（web/worker）、PostgreSQL、ClickHouse、Redis 和 MinIO，遵循[官方部署拓扑](https://langfuse.com/self-hosting/deployment/docker-compose)。[SDK v5 要求服务 v4](https://langfuse.com/docs/observability/sdk/overview)。基础设施镜像标签仍可能更新，正式复现实验前应记录实际镜像 ID/digest。

不要输出不带 `--quiet` 的 Compose 展开配置，它包含本地密码。停止本项目用相同参数执行 `stop`；保留数据，不使用全局 `prune` 或删除其他项目卷。

### 镜像下载故障

初次 Docker 官方入口返回 EOF，配置镜像源还出现过 layer 大小不匹配，Docker 已拒绝该内容。后续通过 localhost:7890，从官方 registry 按镜像层断点续传，并在匿名拉取令牌过期后刷新；逐层校验 SHA-256 后离线导入，剩余镜像已下载完成。镜像清单 digest、导入后的 ID 和文件系统层一致性均已留证。本轮未更改全局 Docker 代理或重启 Docker。

如果日后需要调整代理，在 Docker Desktop 的代理设置中使用受支持方式配置，保存前先确认不会中断其他任务；仅设置终端 `HTTP_PROXY` 不会自动改变 daemon 的拉取路径。不要关闭 TLS/digest 校验，不必为了下载失败重新生成凭据。

## 3. 为一次 Issue 执行启用追踪

服务健康后，在启动 CLI 或任务服务的同一个终端设置：

```powershell
$env:CORECODER_LANGFUSE_ENABLED='1'
$env:CORECODER_LANGFUSE_ENV_FILE='D:\project_other\CoreCoder\.tmp\langfuse-local\.env'
$env:NO_PROXY=@($env:NO_PROXY,'127.0.0.1','localhost','::1') -join ','
python -B -m repairflow demo-issue --entry .tmp/issue-mvp-starter-20261029/catalog/sample --output .tmp/langfuse-demo-001
```

示例条目来自[自包含合成演示](issue-service.md)，输出目录必须是新目录；该演示运行 CLI/API、审批恢复、Docker 公开检查，模型调用为零。也可在启用变量后启动既有任务服务；Worker 继承此配置。不要为了接入追踪重跑历史 50 项模型实验。

读取执行目录中的 `observability.json`，或 API 的 `GET /tasks/{id}/artifacts/observability.json`；`report.json` 与任务结果也包含该状态。

| 状态 | 含义 |
| --- | --- |
| disabled | 未启用，不导入 SDK、不发请求 |
| unavailable | 配置、SDK 或连接初始化不可用，任务继续 |
| submitted_unconfirmed | SDK 已调用 flush；尚未独立确认服务器存储 |
| partial | 观测过程中发生异常，局部记录可能不完整 |

**服务验收必须回读：**打开返回的 Trace 链接或查询服务器观测 API，确认根节点及模型/工具/检查子节点、父子关系与状态。合成任务应为 `fresh_model_calls=0`、`accepted=false`。只看到链接或 `submitted_unconfirmed` 不能宣布部署验收完成。

用同一演示输出目录执行可复现的回读检查；输出文件必须是新文件：

```powershell
python -B -m deploy.langfuse.verify --demo .tmp/langfuse-demo-001 --env-file .tmp/langfuse-local/.env --output .tmp/langfuse-receipt-001.json --timeout 120
```

验证器查询实时 observations v2 与 scores v3，核对核心节点、每类操作数量与本地 Trace 一致、全部节点结束、子节点指向正确根节点、I/O 摘要白名单及三项评分。支持 SDK 的逻辑根节点保留外部物理父节点，不误判为树损坏。服务器确认另存到回读报告，不改写原始 `submitted_unconfirmed` 状态。

本次已完成的演示输出为 `.tmp/langfuse-server-demo-20261029`；首次和重启后回读证据见[服务验收](langfuse-server-20261029.md)。账号密码仍只在 `.tmp/langfuse-local/login.txt`。

禁用后恢复原流程：`Remove-Item Env:CORECODER_LANGFUSE_ENABLED`。本轮不包含 Langfuse 数据集同步、自动实验对比、告警或 LLM 裁判；其他四项路线见[前沿能力接入](advanced-capabilities.md)。
