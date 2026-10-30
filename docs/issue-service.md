# 新 Issue 服务与完整演示

本轮优先交付可运行的工程版本，准确率优化后置。当前支持管理员指定的 Python 仓库，CLI 与 API 共用修复执行器。

```text
Issue URL + 可信配置 → 固定源码与 Docker 准入 → 可信目录注册
→ HTTP 幂等提交 → 待审批 → 批准 → 独立 Worker
→ 读取代码 → 生成候选 → 补丁校验 → Docker 测试与反馈
→ ready_for_review / failed → 下载补丁、报告和 Trace
```

模型提出 JSON 动作，执行器负责实际读写和测试。操作发生在任务副本，不覆盖原仓库。审批针对开始执行；最终补丁仍由用户审查，不自动提交、推送或合并。

## 环境

使用已有 corecoder Conda 环境、Docker Linux containers 和本地 `corecoder-test-sandbox:v1` 镜像。运行时不拉取镜像或安装仓库依赖。本机 SQLite 扩展位于 D 盘；干净环境需安装项目已有的 service/workflow/dev extras。

```powershell
Set-Location D:\project_other\CoreCoder
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
$env:CORECODER_HOME='D:\project_other\CoreCoder\.tmp\issue-service-state'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
$env:CORECODER_LIVE_SMOKE=''
```

新增产物均放 D 盘，不操作已有 8001 服务。演示可用 `--image <固定内容ID>` 选择现存镜像。

## 无需模型的完整演示

```powershell
python -B examples/create_issue_demo.py --output .tmp/issue-demo-input-001
python -B -m repairflow demo-issue --entry .tmp/issue-demo-input-001/catalog/sample --output .tmp/issue-demo-run-001
```

第一条创建**合成工程任务**、运行真实 Docker 准入并注册。它不依赖历史 50 项数据，不抓取 GitHub、不调用模型。仓库名、全零 commit 和 Issue URL 是本地夹具身份，不是实际缺陷来源；准备记录标记 `synthetic_offline_demo_no_http`。

第二条先运行 CLI，再通过 ASGI HTTP 客户端驱动真实应用及 Worker，核对幂等提交、审批前不执行、服务重建后恢复审批、批准后执行、CLI/API 补丁一致、重复批准不再次执行、拒绝后不执行、SSE 与制品下载。

结果位于 `acceptance.json` 和 `evidence/`。`status=passed` 表示工程演示验收通过；`independent_acceptance=false`，不代表独立证明修复正确。脚本响应的 `fresh_model_calls=0`，不能计入模型准确率。所有命令拒绝覆盖旧目录，复现请换新目录。

## 真实 Issue 与目录注册

管理员审查仓库、固定 commit、镜像、代码范围和公开检查后：

```powershell
python -B -m repairflow import-issue --url https://github.com/pallets/click/issues/3887 --config configs/issue-tasks/click-3887.json --output .tmp/issue-prepared/click-3887-001
python -B -m repairflow register-issue --prepared .tmp/issue-prepared/click-3887-001 --config configs/issue-tasks/click-3887.json --output .tmp/issue-tasks/click-3887
```

可以复用已准入、哈希未变的准备目录。注册复制源码、准入记录、相对路径配置及检查为自包含目录。服务仅接收任务 ID，不接受客户端路径、测试上传、Shell 或工具配置。

可选 `--responses <文件>` 由管理员加入脚本响应用于离线演示；否则任务只开放 `live`。注册时固定本地模型名，HTTP 客户端不能更换。API 的 `live` 使用本地 Ollama、关闭 thinking，不加载 DeepSeek 配置。

### 只读依赖与可写文件

配置增加可选 `read_only_files`，例如以下片段（其他字段仍须保留）：

```json
{
  "allowed_files": ["src/click/termui.py"],
  "read_only_files": ["src/click/_compat.py"]
}
```

两份列表明确、互不重叠，无重复、通配符、路径越界或 `.env`。依赖可通过 `read_symbol` 读取，但即使获得原文回执也不能修改。导入声明不自动扩大权限。配置变化必须用新目录重新准入，不能修改已审批范围。

工具循环目前为 `read_symbol`、`apply_patch`、`finish`，有效编辑后自动运行可信公开测试；尚不提供通用自主搜索或任意 Shell。

## 浏览器/API

用合成任务展示完整链路：

```powershell
$env:CORECODER_ISSUE_TASKS='D:\project_other\CoreCoder\.tmp\issue-demo-input-001\catalog'
python -B -m service --port 8004 --timeout 1200 --output .tmp/issue-http-001
```

打开 `http://127.0.0.1:8004/docs`。另一个终端提交：

```powershell
$base='http://127.0.0.1:8004'
$body='{"suite":"issues","task_id":"sample","mode":"scripted","workflow":"issue-approval-v1"}'
$task=Invoke-RestMethod "$base/tasks" -Method Post -ContentType application/json -Headers @{'Idempotency-Key'='issue-demo-001'} -Body $body
Invoke-RestMethod "$base/tasks/$($task.id)"
# 到 awaiting_approval 后再批准；等待期间可重启服务确认审批恢复。
Invoke-RestMethod "$base/tasks/$($task.id)/artifacts/workflow.json"
Invoke-RestMethod "$base/tasks/$($task.id)/approval" -Method Post -ContentType application/json -Body '{"decision":"approve"}'
```

轮询到 `ready_for_review` 或 `failed` 后下载：

```powershell
Invoke-RestMethod "$base/tasks/$($task.id)/artifacts/report.json"
Invoke-RestMethod "$base/tasks/$($task.id)/artifacts/patch.diff"
```

真实 Issue 改用 `.tmp/issue-tasks` 目录及对应任务 ID。`mode=live` 才会启动本地模型，不属于离线演示。

| 接口 | 用途 |
| --- | --- |
| `GET /health` | 存活检查，不检查模型或承诺沙箱就绪 |
| `GET /catalog` | 可信任务与允许模式 |
| `GET /tasks`、`GET /tasks/{id}` | 任务列表与状态 |
| `POST /tasks` | 幂等提交 |
| `POST /tasks/{id}/approval` | 执行前 approve/reject |
| `POST /tasks/{id}/cancel` | 取消任务、终止 Worker 并清理对应容器 |
| `GET /tasks/{id}/events` | SSE 生命周期状态，支持 Last-Event-ID |
| `GET /tasks/{id}/artifacts/{name}` | 白名单制品下载 |

制品白名单：`workflow.json`、`report.json`、`patch.diff`、`trace.jsonl`、`provenance.json`、`actions.json`、`agent-initial-context.json`、`observability.json`。不提供脚本回答、检查点数据库、配置或任意路径下载。

可选 [Langfuse 本地追踪](langfuse-local.md)记录任务、模型、工具和 Docker 检查的父子节点；在启动服务前设置启用变量及连接文件。默认关闭，连接失败不改变修复结论，上传结构化摘要而非源码或原始日志。[本地服务接收、登录和重启保留已验收](langfuse-server-20261029.md)，不影响未启用 SDK 的离线运行。

`ready_for_review` 是结束状态，`accepted` 仍为 false。失败任务保留原因并回滚净补丁；中断任务不自动重放已启动的执行。SQLite 保存任务/事件，LangGraph 保存审批，哈希绑定原任务，防止等待期间替换输入。

## 验收与限制

本轮[验收记录](issue-mvp-20261029.md)：全量 **1,823 passed、20 skipped**；单独启用的真实 Docker **8 passed**；自包含 CLI/API 离线演示通过。未调用模型，不更新历史准确率。

```powershell
$env:CORECODER_RUN_DOCKER_TESTS='1'
python -B -m pytest tests/test_issue_service_docker.py tests/test_issue_repair_docker.py -q
```

当前是本地单实例、源码运行、Swagger 演示的工程版本。独立前端、多租户认证、分布式队列、任意仓库依赖适配、GitHub 发布和新准确率实验均后置。未实现的功能不影响当前指定任务的完整流程验收，但不能表述为通用生产平台。
