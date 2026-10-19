# 已准备 Issue 的修复与公开验证

## 本阶段交付

`repairflow repair-issue` 将已准备的真实 Issue 接入候选补丁、Docker 验证、最多一次反馈修正和结果报告。
它复用现有符号上下文选择和唯一锚点补丁约束，不创建假的隐藏评分器。

```text
import-issue → 固定源码 + 可信公开测试 + 准备证据
repair-issue → 校验准备材料和管理员配置 → 再次确认原始缺陷
             → 选择上下文 → 结构化补丁 → 范围/版本/锚点/语法校验
             → Docker 公开测试 → 必要时一次反馈修正
             → 保留待审查补丁，或回滚并输出失败报告
```

目前是 CLI；尚未接入新任务的 HTTP 审批入口、主动搜索工具循环或 GitHub 发布。
旧可信任务包的 `run --mode live/replay` 保留原协议，新入口不改变其历史实验成绩。

## 两种明确选择的执行模式

| 模式 | 用途 | 模型调用 |
| --- | --- | --- |
| `scripted` | 用一至两份手工指定响应验收执行链路 | 零；不代表模型修复效果，不填造 Token 用量 |
| `ollama` | 后续使用本机已安装模型进行新推理 | 仅固定环回地址的原生 Ollama API；显式 `think: false` |

本轮只运行 scripted 验收，不请求本地或付费模型。
Ollama 请求不加载 `.env`、不读取云端 API Key、禁用代理环境和重定向；显式云模型名称被拒绝。
运行前应确认本机 Ollama 服务及模型由操作者管理；环回地址本身不证明服务值得信任。
无思考参数及完成状态按 [Ollama chat API](https://docs.ollama.com/api/chat) 处理。
截断、意外思考内容、工具调用或网络故障均停止，不将半份响应应用到源码。

## 使用方式

沿用 [README](../README_CN.md) 的 D 盘环境变量。先完成 [Issue 准备](github-issue-preparation.md)，
再使用**原始、未修改的可信配置**启动修复：

```powershell
# 仅在需要实际本地推理时手工运行；本轮验收不执行此命令。
python -B -m repairflow repair-issue --prepared .tmp/github-issues/click-3887 --config configs/issue-tasks/click-3887.json --output .tmp/issue-repairs/click-3887-001 --mode ollama --model qwen3.5:27b
```

输出目录必须全新，不能与准备任务、配置目录或响应文件重叠。
Docker 和镜像条件在模型调用前检查；镜像内容 ID 必须与准备阶段一致。
即使环境设置了 `CORECODER_TEST_BACKEND=local`，该入口也不会退回宿主机测试。
若本机镜像标签无法查询，先修复镜像标签，或在可信配置中改用已核对的镜像 ID 并重新准备任务；不能静默换镜像。

手工响应模式的 `--responses` 文件是一个 JSON 数组，含一至两个**字符串**；每个字符串本身是补丁 JSON：

```json
[
  "{\"edits\":[{\"file\":\"src/pkg/__init__.py\",\"old\":\"    return x + 1\",\"new\":\"    return x + 2\"}]}"
]
```

以上补丁仅适用于自包含测试 fixture，不是 Click 修复。对准备任务使用相应候选响应：

```powershell
python -B -m repairflow repair-issue --prepared .tmp/my-prepared-issue --config .tmp/my-trusted-config/task.json --output .tmp/issue-repairs/scripted-001 --mode scripted --responses .tmp/my-responses.json
```

不依赖旧 `.tmp` 实验资产的验收命令：

```powershell
python -B -m pytest tests/test_issue_repair.py tests/test_github_issue.py -q -p no:cacheprovider
$env:CORECODER_RUN_DOCKER_TESTS='1'
python -B -m pytest tests/test_issue_repair_docker.py -q -p no:cacheprovider
```

## 结果不能混淆

| 条件 | 状态与交付 |
| --- | --- |
| 候选代码的 Reproduce、Preserve 都通过，且修改范围、输入完整性有效 | `status=public_checks_passed`、`delivery_status=ready_for_review`，保留 diff |
| 测试未通过、补丁无效、预算超限或执行故障 | 不交付候选；恢复任务工作区，最终 `patch.diff` 为空 |
| 没有独立评分材料 | 始终 `accepted=false`、`independent_verification.available=false`、`passed=null` |

CLI 退出码 0 表示“公开检查通过、可供人工审查”，不表示独立验收成功。
模型生成的测试不被提升为独立正确性依据；当前解释器内测试也不具备完全防评分篡改保证。
公开复现规格仍由操作者审查，例如 Click #3887 目前采用报告者预期，不代表上游已经接受该语义。

## 限制与证据

- 最多两次候选生成：初次加一次反馈；总 Token 记账上限 60,000，单次输出上限 32,768，上下文 65,536。
- 保留估算预检和返回用量记账；不是服务商计费硬上限。脚本响应无实测 Token，按预留额度保守记账。
- 阶段间检查 1,200 秒任务期限；本地请求不超过剩余时间和 480 秒，每个测试组沿用 Docker 的独立超时与资源限制。
- 沙箱故障不作为代码失败要求模型反复修改；参考修复和独立评分材料不会进入该流程。
- `provenance.json` 保存 Issue、commit、输入/配置哈希、镜像、预算、模式和新执行模块哈希。
- `initial/correction-*` 保存实际上下文、请求、响应、候选 diff 和公开检查日志；失败候选的诊断材料保留。
- `report.json` 区分脚本调用、本地真实模型调用、未知用量、公开测试和独立验收；`trace.jsonl` 保存阶段与调用事件。
- 原始准备任务不被写入；候选始终位于新任务目录。不自动 commit、push 或发布 PR。

尚未进行新 Issue 的真实模型修复实验，因此不新增修复率，也不与历史 47/50 合并统计。

## 本轮验收（2026-10-19）

- 相关回归 **200 passed，0 failed，0 skipped**，含 32 项新单元/CLI/接口契约测试、2 项新真实 Docker 用例及既有沙箱/服务/审批回归。
- 两项新 Docker 用例使用自包含 fixture：有效候选进入待审查状态；错误候选经过最多一次修正后回滚。均无模型请求。
- 复用已准备的真实 Click #3887，手工指定一份能应用但不改变缺陷行为的候选；实际 Docker 验证确认目标仍失败、3 项正常行为检查通过，最终拒绝交付、恢复源码并清空最终 diff。
- 上述 Click 用例是负向执行验收，不代表模型尝试修复失败，也不是新增模型修复成绩；初次候选 diff 和诊断材料仍保留。
- 本机已有沙箱镜像标签查询再次失效；将同一已核对内容 ID 重新赋予原标签后，查询恢复。未构建或拉取镜像，根因仍未确定；相关回归使用固定镜像 ID。
- 实际模型调用为零；原始 Issue 准备数据、历史实验和 8001 服务不改动，全部新增状态与报告位于 D 盘。

结构化结果见 [验收摘要](prepared-issue-repair-acceptance.json)。本地原始产物位于 `.tmp/issue-repair-acceptance-20261019/`。
