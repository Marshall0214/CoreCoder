# Docker 沙箱真实验收（2026-10-19）

## 交付范围

完成计划 P0：本地 CLI/FastAPI 统一修复流程使用真实 Linux 容器执行测试，
验证运行限制、取消/恢复清理，并以历史 Click 任务贯通离线演示。
没有调用 DeepSeek、Ollama 或其他模型，没有发起新的 thinking 推理。

Docker 虚拟磁盘确认在 `D:\Users\admin\AppData\Local\Docker\wsl\DockerDesktopWSL`。
仅构建 `deploy/sandbox` 上下文；模型密钥、仓库源码未作为镜像构建上下文发送。
原有 8001 服务未停止或重启，API 演示使用 ASGI 客户端和真实子进程。

## 本次修正

1. **tmpfs 结果生命周期。**测试进程直接作为容器主进程时，退出会导致 /tmp 卸载，无法读取结果。
   改为容器保持进程与测试 exec 分开；测试结束后读取结果，再删除容器。
2. **tmpfs 结果传输。**本机 Docker archive/cp 接口无法取得该 tmpfs 文件。
   改为容器存活时通过 tar 输出一个受限大小的结果归档，宿主仅解析，不解压。
3. **执行退出码与 OOM。**exec 后不再把容器保持进程的退出码当作测试退出码；
   结合 exec 状态、容器 OOM 状态及可用的 cgroup 事件区分失败。
4. **真实限制验收。**资源测试同时支持 cgroup v1/v2；本机运行 cgroup v1，不能硬编码 v2 文件路径。

容器保持进程寿命上限 300 秒，测试保留 15 秒期限，外层 exec 等待 20 秒。
发生异常仍执行容器删除；这不改变模型、反馈次数或独立评分的成功条件。

## 验收覆盖

最终相关回归：**163 passed，0 failed，0 skipped，164.86 秒**，其中 9 项真实 Docker 用例。
Ruff 检查通过；Docker Engine 28.1.1，Linux，cgroup v1。

| 用例 | 检查内容 |
| --- | --- |
| 公开与独立测试 | Reproduce/Preserve、Target/Controls 在不同容器执行 |
| 文件与网络 | 代码/测试/根目录不可写、密钥不继承、外网连接被阻止 |
| 沙箱离线回放 | 固定响应夹具生成补丁并通过独立验收，模型调用为零 |
| 超时 | sleep 超过 15 秒被终止，容器删除 |
| 日志超限 | 超过 1 MiB 被中止，日志大小受限，容器删除 |
| OOM | 超出 1 GiB 触发内存限制，正确报告并删除容器 |
| CPU/进程 | 实际 cgroup 限制为 1 CPU、1 GiB、64 进程；进程创建被限制 |
| API 取消 | 工作进程被停止后，对应 Docker 容器也被清理 |
| 中断恢复 | 恢复时清理对应任务容器，其他任务容器保持运行 |

测试代码：[真实 Docker 用例](../tests/test_sandbox_docker.py)。
最终回归统计、镜像 ID、无遗留容器检查和证据哈希见 [验收摘要](sandbox-acceptance-20261019.json)。
该记录为相关回归，不是全仓库测试或新的 50 任务模型评测。

## 完整历史任务演示

任务：`click-usage-empty`，使用既有认证任务包及历史单次模型响应。
CLI 与 API 均通过代码检索、补丁校验、真实 Docker 检查与独立验收，最终 diff 一致。
API 还覆盖幂等提交、审批重启恢复、SSE、证据下载与拒绝审批不执行。
两条流程共执行 20 组容器检查，全部完成；实现哈希与运行证据一致，最终无遗留沙箱容器。

原始证据：`.tmp/sandbox-acceptance-20261019/demo/acceptance.json`、
`demo/cli/report.json`、`demo/evidence/report.json`、`demo/evidence/events.sse`。
这些输出位于 D 盘，摘要保存在 docs，供 .tmp 未提交时说明验收口径。

## 复现

环境及构建步骤见 [执行沙箱](execution-sandbox.md)。在 corecoder 环境设置 D 盘临时目录后：

```powershell
$env:DOCKER_CONTEXT='desktop-linux'
$env:CORECODER_TEST_BACKEND='docker'
$env:CORECODER_RUN_DOCKER_TESTS='1'
python -B -m pytest tests/test_sandbox_docker.py -q -p no:cacheprovider
python -B -m repairflow demo --bundle .tmp/repair-bundles/click-usage-empty --output .tmp/sandbox-demo-new
```

回放需要已有任务包；没有历史数据时可先运行自带测试夹具的 Docker 用例。
重复演示使用新输出目录，不覆盖旧证据。

## 边界与下一步

这次验证的是任务级容器隔离和执行流程，不是虚拟机级隔离，也不解决同解释器评分欺骗。
历史响应的 Token 只是旧调用记录，不计为新增推理消耗；历史 47/50 成绩保持不变。
旧 Agent Bash/旧 evals 尚未统一到此后端，最新整套服务镜像部署仍属后续工作。
下一步为 P1 的只读 GitHub Issue 导入、可信仓库配置和任务准备；继续不调用模型 API。
