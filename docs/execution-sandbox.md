# 修复测试执行沙箱

CLI/API 的统一 `repairflow` 流程默认在独立 Docker Linux 容器中执行每组公开测试和独立验收。
模型调用、检索和结构化补丁应用仍在服务进程；容器没有 API Key，不调用模型。
历史实验、旧 evals 模式和原始 Agent 的 Bash 工具没有因此自动获得沙箱。

## 使用

Docker Desktop 的数据目录必须保持在 D 盘。先启动 Docker Desktop 并切换至 Linux containers。
以下命令在仓库根目录的 PowerShell、corecoder 环境运行：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
$env:DOCKER_CONTEXT='desktop-linux'
docker build -f deploy/sandbox/Dockerfile -t corecoder-test-sandbox:v1 deploy/sandbox
$env:CORECODER_TEST_BACKEND='docker'
$env:CORECODER_SANDBOX_IMAGE='corecoder-test-sandbox:v1'
$env:CORECODER_RUN_DOCKER_TESTS='1'
python -B -m pytest tests/test_sandbox_docker.py -q -p no:cacheprovider
python -B -m repairflow run --bundle .tmp/repair-bundles/click-usage-empty --mode replay --output .tmp/repair-demo/sandbox-replay-v1
```

镜像构建可能下载 Python 基础镜像，不使用模型 API。测试执行只使用本地镜像，不拉取、不安装依赖。
当前任务包使用 stdlib unittest 与随包仓库代码；其他仓库需要把明确的依赖预装到镜像。
基础镜像标签需在正式发布时固定为经过验证的 digest；每次修复已固定并记录实际本地 image ID。
重复运行请换新输出目录。离线历史回放不是一次新的模型推理，也不构成修复率提升证据。

启动 API 时继承以上环境，使用独立端口，避免影响 8001 的现有服务：

```powershell
python -B -m service --port 8004 --timeout 1200 --output .tmp/repair-service-sandbox
```

审批、幂等提交、SSE、证据下载方式见 [统一流程](unified-repair-flow.md)。
当前旧版服务 Dockerfile 未包含完整统一流程依赖；此方案是本地服务调度独立测试容器，
不要给 Web 服务挂载 Docker Socket 来绕过这一部署限制。

## 执行策略

- 每组测试一个临时容器，公开测试与独立评分材料分别挂载，不共享执行实例。
- 非 root UID 10001、只读根目录、移除全部 capabilities、no-new-privileges。
- network none；没有宿主网络、Docker Socket 或模型密钥挂载。
- 代码、测试、执行器只读挂载；只有限额 128 MiB 的 /tmp 可写。
- 1 CPU、1 GiB 内存且不额外使用 swap、64 进程。
- 测试内部 15 秒期限；Docker exec 外层 20 秒，控制调用另有超时。
- stdout/stderr 合计最多 1 MiB，不使用无限增长的 Docker 日志文件。
- 评分文件从容器 /tmp 读取：限制传输大小，仅接受一个小型普通 JSON 文件，不解压路径或链接。
- 正常退出、异常、超时都会尝试删除容器；API 取消、任务结束及恢复中断任务时按精确任务标签清理。
- Docker 不可用或镜像不存在时在调用模型前失败，不自动降级。执行故障不作为代码错误反馈让模型重试。
- 容器失败的诊断保存在每组 `*-sandbox.json`，清理失败会阻止通过。
- 运行期间基础设施失败会回滚候选修改，输出失败报告；启动预检失败则不创建运行输出。

容器先启动有 300 秒寿命上限的保持进程，再通过 exec 执行测试。
测试退出后容器暂时保持运行，用限量 tar 流读取 /tmp 中的结果并校验，随后删除容器。
不能先停止容器再读结果：tmpfs 会随停止卸载，且当前 Docker archive/cp 接口无法取得该挂载内的文件。
宿主机不解压返回的归档，也不增加可写宿主输出挂载。

明确的开发选项 `CORECODER_TEST_BACKEND=local` 保留旧子进程执行，**不具有安全沙箱隔离**。
既有单元和 API 回归测试显式使用该模式；真实 Docker 集成测试必须单独开启，不把跳过算验收通过。

## 边界

这提供容器级执行隔离，不是虚拟机级隔离或对任意恶意租户的完整防护。
当前只接收可信任务包；仓库构建、依赖安装不能在宿主机执行不可信脚本。
测试和候选模块仍在同一 Python 解释器中，候选代码理论上可干预 unittest 或伪造输出；
结果格式和只读材料校验不等于解决评分欺骗，也不能将私有测试内容视为对候选代码保密。
不得把“宿主机隔离”和“评分完全防篡改”混为同一保证。

## 历史验证（2026-10-13）

未调用 DeepSeek 或其他模型 API。Docker 引擎初次检查不可用，真实容器集成暂未验收；
离线单元测试覆盖策略、失败关闭、输出限额、超时、归档校验、错误分类及精确清理。
真实集成用例已提供，运行后应补记实际结果，再声称容器隔离已验收。

2026-10-13 相关回归：**154 passed, 3 skipped**，71.75 秒；Ruff 通过。
跳过的三项是公开/独立验收、真实容器文件和网络限制、Docker 历史回放端到端验收。
该数量不代表全仓库测试，也不代表 Docker 验收通过。

## 真实验收（2026-10-19）

已启动 Docker Linux 引擎，确认虚拟磁盘位于 D 盘；构建本地镜像并运行真实容器测试。
验收覆盖公开/独立检查、文件只读、密钥不继承、禁网、超时、日志超限、OOM、CPU/进程限制，
以及 API 取消清理和服务重启时只清理对应任务容器。兼容本机 cgroup v1 的限制读取。

历史 Click 任务经 CLI 和真实 API 子进程的完整 Docker 回放通过，补丁一致；
包含审批恢复、幂等、SSE、证据下载及审批拒绝不执行。没有新模型调用或 thinking 推理。
API 演示使用 ASGI 客户端，并非浏览器/TCP 端口验收；旧 47/50 模型实验成绩不变。

详细结果与复现入口见 [2026-10-19 验收报告](sandbox-acceptance-20261019.md)。
最终相关回归 163 项通过，含 9 项真实 Docker 用例，无跳过；不代表全仓库测试。
