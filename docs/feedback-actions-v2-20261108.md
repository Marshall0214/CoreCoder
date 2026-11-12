# 反馈动作循环 v2：重新读取、编辑与公开验证

状态（2026-11-09）：P2 反馈动作循环验收完成。38 项离线测试与 3 项真实 Docker 测试通过，独立 CLI 回放通过；协议名为 `public-feedback-actions-v2`。本阶段使用录制响应，真实模型调用为 0，不产生新的修复率结论。同日后续[上下文与 Schema 接口验收](feedback-context-contract-20261109.md)单独归档；真实 Issue 模型运行及 Harness² 接入仍为后续工作。

## 本次解决什么问题

旧反馈入口每次发送全部允许修改的源码，只接受补丁，遇到报错后无法重新搜索或读取关联定义。新增独立模块 `repairflow/feedback_repair_v2.py`，让反馈阶段按需取得当前代码证据，再编辑并自动执行公开检查。旧入口默认行为、初始探索和 Harness² 接入不变。

```text
当前候选 → 公开检查 → 失败 → 搜索/读取 → 编辑 → 自动公开检查
                       ↑                    ├─ 通过：待审查
                       └─ 错误反馈/回滚 ←───┘
```

公开通过只表示满足冻结的开发检查。独立 Target/Controls 不传入本入口，也不参与修正；仍须在任务终止、候选冻结后另行评分。

## 执行合同与保护

- 一次响应只允许一个 `{action, arguments}` 对象，支持 `list_files`、`search`、`read_file`、`read_symbol`、`apply_patch`、`finish` 六种动作；没有 shell、网络或独立评分工具。
- 默认最多 **20 次反馈请求**；搜索、读取、补丁、格式错误和主动结束都计数。工具执行与自动检查不隐式增加模型调用；这不是 20 次有效修复，也不包含此前探索请求。
- 可读与可编辑 Python 文件白名单分开；允许读取不代表允许修改。模型只收到当前收据和近期观察，不再自动重发全部源码。文件和符号读取按字符分页，明确是否完整。
- 收据携带路径、文件哈希、范围、工作区 revision 与 receipt ID。编辑须提交当前 revision，原文须来自有效收据并唯一匹配；成功编辑或回滚后旧收据失效。
- 补丁先在暂存视图检查字段、锚点和语法，再发布；多文件发布中途失败会恢复修改前快照。恢复异常明确报告控制器故障，不继续宣称修改成功。
- 修改后自动公开验证。仅当 Preserve 从修改前通过变为修改后失败时，保存失败补丁和验证证据，恢复修改前候选、增加 revision，并将回滚事实反馈给模型。原本失败不等于新引入回归。
- 仅明确的 `sandbox_start_failed`、`sandbox_runner_start_failed` 可按相同候选哈希重试一次；断言失败不做环境重试。各次验证保留记录，并核对沙箱镜像与资源身份。
- 验证使用独立 worker。取消、超时或异常退出时终止所属进程树，按本次 owner 标签清理容器，不清理其他任务。清理失败单独留痕。同步 `chat` 目前只能在响应返回后协作取消，不能宣称立即中断模型计算。

## 证据与计数

每次运行保存协议、输入与源码哈希、实际请求、原始响应、动作报告、补丁、worker 输出和逐次公开验证结果；原始 baseline、candidate、public-checks 导出保持不变。

报告分别计数：请求、成功读取、成功搜索、补丁尝试、已应用补丁、公开验证尝试、环境重试和回滚。无原生 Token 用量时保留 `null`；录制响应的真实模型调用数为 **0**。

最终候选哈希关联对应的已完成验证记录。若取消或环境故障留下未验证补丁，候选仍保存，但明确标为待验证；历史已验证记录保留，不能把其他版本的通过结果套到当前候选。

## 当前验收（2026-11-09）

- 离线测试 **38 项通过**：v2 动作循环 22 项、验证 worker 5 项、旧反馈入口兼容 11 项。结果来自 11 月 8 日；本次补验核对源码哈希未变，未重复运行这组测试。Ruff 与 CLI `--help` 亦已通过。
- 环境恢复后，真实 Docker **3 passed / 30.07 秒**。完整回放完成 **5 次请求、3 次读取、2 次补丁、3 次公开验证**，无环境重试或回滚。按验证记录实际顺序，`Reproduce/Preserve` 为 **失败/失败 → 失败/通过 → 通过/通过**，6 个公开检查组均取得真实容器结果。
- 完整回放在首次逻辑错误补丁之后，按需读取依赖符号与当前函数，再应用正确补丁。读取收据对应 revision 0、1、1；最终候选哈希关联通过的验证记录，原始 baseline、candidate、public-checks 保持不变。
- 两项真实取消验收分别覆盖：响应返回后取消，阻止补丁落盘和额外验证；公开验证运行中取消，终止验证 worker 并确认所属容器清理完成。同步模型请求的即时取消仍不在本次证明范围。
- 独立录制 CLI 返回 `ready_for_review`、`accepted: true`、退出码 0；同样完成 5 次请求、2 次补丁、3 次验证，真实模型调用为 0。汇总、源码与制品哈希见 `.tmp/feedback-v2-20261109/acceptance-summary.json`，pytest 原始结果见 `docker.xml`，CLI 结果见 `cli-demo/report.json`、`cli-output.txt` 与 `cli-exit.txt`。
- 20 次边界、读写权限、分页、畸形动作、陈旧收据、多文件发布失败恢复、保持性回滚、环境启动重试和 worker 异常清理由离线测试覆盖；不将它们全部描述为已做真实容器验收。

历史失败保留：11 月 8 日两次真实 Docker 执行分别为 **3 failed / 5.70 秒**、**3 failed / 153.82 秒**；原始 XML 位于 `.tmp/feedback-v2-20261108/docker.xml`、`docker-retry.xml`。当时 Docker API/验证启动不可用，停止盲目重跑；本次在 D 盘空间与 Docker API 恢复后另建目录补验，没有覆盖失败记录或修改历史成绩。

## 录制响应入口

CLI 当前强制 `--responses`，只回放动作。以下复用本次验收生成的三文件示例；从项目根目录、现有 `corecoder` 环境执行，输出必须使用尚不存在的 D 盘目录。重复执行时更换输出后缀，保留已有记录。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTHON_DOTENV_DISABLED='1'
$env:CORECODER_LANGFUSE_ENABLED='0'
$env:TEMP='D:\project_other\CoreCoder\.tmp\feedback-v2-20261109'; $env:TMP=$env:TEMP
$fixture='.tmp/feedback-v2-20261109/docker/test_recorded_feedback_relocat0'
python -B -m repairflow.feedback_repair_v2 `
  --baseline "$fixture/baseline" --candidate "$fixture/candidate" `
  --public-checks "$fixture/public" --package pkg `
  --task .tmp/feedback-v2-20261109/task.json --responses "$fixture/responses.json" `
  --allowed pkg/calc.py --readable pkg/calc.py pkg/rules.py pkg/__init__.py `
  --output .tmp/feedback-v2-20261109/cli-replay --max-feedback-rounds 20 --timeout 1200
```

`task.json` 仅包含 `instance_id`、`repo`、`base_commit`、`problem_statement`；`responses.json` 是动作 JSON 字符串组成的数组，而非动作对象数组。若源码位于 `src/`，补充 `--source-root src`，文件白名单仍使用导出根目录相对路径。

## 重复真实容器验收

确认 D 盘有运行余量，`docker info` 返回 `linux` 与非空服务版本、stderr 无 API 错误，且原沙箱镜像 ID 不变，再执行下列三项用例。使用新目录保留既有结果；无需拉取镜像或调用模型。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTHON_DOTENV_DISABLED='1'
$env:CORECODER_RUN_DOCKER_TESTS='1'; $env:CORECODER_LANGFUSE_ENABLED='0'
$env:TEMP='D:\project_other\CoreCoder\.tmp\feedback-v2-20261109'; $env:TMP=$env:TEMP
python -B -m pytest tests/test_feedback_repair_v2_docker.py -q `
  --basetemp .tmp/feedback-v2-20261109/docker-replay `
  -o cache_dir=.tmp/feedback-v2-20261109/pytest-cache `
  --junitxml .tmp/feedback-v2-20261109/docker-replay.xml
```

三项分别覆盖完整录制修正链路、响应后取消、公开验证运行中的进程与容器清理。上下文和动作 schema 的同日后续验收见[单独记录](feedback-context-contract-20261109.md)，下一步为既定五项本地模型机制验证；不自动启动 Harness² 或全量 50 项实验。

## 来源与环境记录

实现：[动作循环](../repairflow/feedback_repair_v2.py)、[工具与补丁校验](../repairflow/issue_tools.py)、[读取收据](../evals/repository_checkpoint.py)、[公开验证器](../repairflow/patch_validator.py)。测试：[v2](../tests/test_feedback_repair_v2.py)、[worker](../tests/test_feedback_validator_worker.py)、[旧入口](../tests/test_feedback_repair.py)、[真实 Docker](../tests/test_feedback_repair_v2_docker.py)。

本次环境维护使用 NTFS 压缩历史文本和静态镜像归档，保留原内容并核对 SHA；另移除一份 SHA256 相同且仍保留副本的可重建镜像缓存 `web-import.tar`，未删除评分、补丁或 Trace。Docker IPC 恢复、两次失败与存储证据位于 `.tmp/feedback-v2-20261108/`。`docker-storage-evidence.json` 记录 12:12:22 的 838 条虚拟存储请求异常、日志哈希和观察边界；未证明 ENOSPC、OOM 或文件系统损坏是根因。环境恢复不属于模型修复能力提升，不能据此修改历史实验成绩。
