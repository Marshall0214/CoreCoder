# 容器部署配置与离线验收

包含主机 [真实 HTTP 服务故障验收](local-http-acceptance-v1.md) 和本轮 Linux 容器验收，两者独立记录。2026-10-07 Docker/Linux 离线部署验收已通过，摘要见 [container-acceptance-v1.json](container-acceptance-v1.json)。

## 本轮交付与当前状态

新增 `deploy/Dockerfile`、Compose、HTTP 健康探针和一键离线验收脚本。runtime 镜像包括 CoreCoder、评测 fixture、服务及 MCP Server；validation 阶段额外安装 pytest 和复制测试辅助模块。运行镜像不包含故障注入测试模块。

**Docker/Linux 离线运行验收已通过。** Docker Server 28.1.1、Compose 2.35.1、Linux/amd64（WSL2）、容器 Python 3.11.17。首次构建 runtime / validation 镜像，Linux 专项 **48 passed（34.70 秒）**；13 项端到端检查、16 条 Docker 命令全部通过，没有真实模型调用。

完整成功记录：`.tmp/deploy-acceptance/5c067f94b2/acceptance.json`，包含命令、构建输出、测试、MCP 演示、HTTP 检查、镜像 ID 及 Linux pip freeze。验收容器和项目网络已移除；任务卷 `corecoder-acceptance-81add40d85_task-data` 保留，原有 8001 服务未停止或重启。

历史失败记录 `.tmp/deploy-acceptance-v1/acceptance.json` 原样保留：当时 Docker Desktop 的 Inference manager 初始化失败，预检查没有通过。该批次不计为成功，也没有重置或删除 Docker 数据。

## 配置行为

| 项目 | 配置 |
| --- | --- |
| HTTP 端口 | 宿主回环 `127.0.0.1:8002` → 容器 8000，避免原服务 8001 |
| 服务进程 | 单 Uvicorn Worker，init 转发信号与回收子进程 |
| 用户/文件系统 | UID/GID 10001、只读根文件系统、可写任务卷及 128 MB 临时目录 |
| 任务状态 | 命名卷挂载 `/app/.tmp/service`，包括 SQLite、事件、日志、补丁与验证产物 |
| 资源限制 | 2 CPU、1 GB 内存、128 PID，移除 capabilities，no-new-privileges |
| 健康检查 | 无第三方依赖的 GET /health，每 5 秒检测；不访问模型 |
| 停止 | 30 秒停止宽限，沿用 lifespan 取消及进程树清理 |

Compose 的 `init`、`read_only`、资源及停止参数、回环端口绑定参考 [Docker 官方服务配置](https://docs.docker.com/reference/compose-file/services/)。这是**整个服务容器**的限制，不是每个候选任务拥有独立容器/凭据/权限隔离；现阶段只接受既有可信 fixture，不能据此宣称能安全运行任意外部仓库。

`.dockerignore` 使用白名单，排除 `.git`、`.env`、实验产物、缓存、学习文档等。镜像源码与容器 root 为只读，任务目录独立于宿主已有 `.tmp/service`。不挂载 Docker socket、宿主用户目录或 Ollama 模型文件；API Key 不通过 Compose 注入。

镜像使用 `python:3.11-slim`，依赖仍按项目声明范围解析。验收脚本记录实际镜像 ID 和 pip freeze；当前尚未固定基础镜像 digest 或生成完整 Linux 依赖锁，不能声称每次构建字节完全相同。之后有真实构建记录再固定版本。

## 启动与 MCP 演示

在 Docker Desktop Linux 引擎 Running、`docker info` 正常的环境中，于项目根目录执行：

```powershell
docker compose -f deploy/compose.yaml config --quiet
docker compose -f deploy/compose.yaml up -d --build --wait
```

打开 `http://127.0.0.1:8002/docs`，提交 `{"task_id":"timeout-units","mode":"scripted"}`；应通过独立验证。`unchanged` 应失败。scripted 是工程链路验收，不代表模型修复能力。

```powershell
# 使用同一运行镜像演示 MCP Client → stdio Server → 搜索/读取。
docker compose -f deploy/compose.yaml run --rm -T --no-deps repair python -m mcp_servers.demo --workspace /app/evals/fixtures/timeout-units/workspace --query timeout

# 保留数据卷重启；历史任务和幂等键应继续可查。
docker compose -f deploy/compose.yaml restart repair

# 停止服务并移除项目容器/网络，保留任务卷。
docker compose -f deploy/compose.yaml down
```

默认项目名为 corecoder-local；部署在自己的命名卷，不与当前本地服务数据混用。无需删除卷来重启服务；删卷会丢失历史和幂等记录。本轮不会自动执行卷删除。

### 模型连接

容器的 localhost 指向容器自身。Compose 将运维配置 `CORECODER_MODEL_BASE_URL` 默认设为 `http://host.docker.internal:11434/v1`，并添加 host-gateway 映射；服务 Worker 读取该环境变量。非容器运行时未设置变量仍沿用 `http://localhost:11434/v1`。客户端任务体不能指定模型地址，模型与 Token 预算仍固定。

Ollama 必须允许 Docker 主机路径访问才能使用 live；本轮未验证这种网络连接，也未执行容器 live。已有实验身份采集仅识别 loopback Ollama，host.docker.internal 地址可能缺少 Ollama 运行身份元数据，因此容器 live 不进入冻结的模型对照成绩。当前默认演示和验收均离线，不需要模型服务。

## 一键离线验收

```powershell
python -m deploy.acceptance
```

脚本创建独立 `corecoder-acceptance-{随机ID}` 项目、自动选择回环端口，按以下顺序执行：

1. 引擎预检查（15 秒超时）、Compose 配置检查，构建 validation 镜像。
2. Linux 容器内运行服务、持久化、MCP 及既有 MCP Client 专项测试；禁用网络，不调用模型。
3. 容器内真实 MCP stdio 搜索/按哈希读取演示。
4. 正常运行镜像的 HTTP scripted 成功、unchanged 失败、产物下载及幂等重发。
5. 重启后检查结果、补丁、幂等键和 SSE 保存。
6. 换用 validation 镜像及测试 Worker，验证运行取消、SIGKILL 后 interrupted，以及同键重发不重启任务。故障注入不计修复能力。
7. 记录镜像 ID、依赖、命令和日志，关闭本次项目容器/网络；保留本次任务卷便于审查。

输出默认为 `.tmp/deploy-acceptance/{运行ID}/acceptance.json`；仅 status=passed 且 checks 全部通过可计入容器验收。命令失败/超时同样保存记录；清理也有超时，并且不会因日志读取失败跳过后续关闭。无需也不会停止原有项目、清理整个 Docker 或删除其他卷。

## 已执行的本地验证

两份 Compose 配置校验通过；部署/服务专项 **25 passed**，涵盖运维模型地址适配、引擎不可用时保存失败且不启动 Compose、命令超时，以及既有服务的持久化/幂等/恢复。全量回归 **838 passed、2 skipped（88.79 秒）**。随后新增日志收集失败仍关闭本次项目的用例，部署专项 **5 passed**；Ruff 和 Git diff 空白检查通过。上述均为本地/配置验证，不能替代尚未执行的 Linux 容器测试。

## 已执行的 Linux 容器验证

- runtime 与 validation 镜像构建成功，运行用户确认为 `10001:10001`；Compose 下只读根、任务卷及临时目录支持真实修复/独立验证。
- Linux 专项 **48 passed、无跳过**：服务、SQLite 持久化、MCP、主机式真实 HTTP 崩溃恢复测试均通过；包括 Windows 曾跳过的符号链接边界测试。
- 容器内官方 MCP Client 的真实 stdio 搜索/读取演示通过。
- 真实容器 HTTP scripted 修复通过独立评分，unchanged 失败；补丁可下载、同键提交不重复创建任务。
- 服务容器重启后，结果、补丁、SSE、幂等键保留；长任务取消通过。
- 故障注入容器 SIGKILL 后，新进程将旧任务标记 interrupted；同键重发保持原 ID，不自动再执行。
- 13 项检查全部通过，验收容器/网络已清理，任务卷及完整命令输出保留。validation 镜像 ID 和 Linux 依赖列表已进入版本控制摘要。

`corecoder/`、`evals/` 和冻结协议没有修改，本轮无需修复源代码。这里只验证可信 fixture 的单服务容器：每任务独立沙箱、负载、远程部署、多用户权限、容器 live 模型连接及完整依赖锁仍未完成。下一步进入结构化工作流，继续保留既有冻结实验方式。
