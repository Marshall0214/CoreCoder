# 已准备 Issue 的修复与公开验证

## 本阶段交付

**2026-10-23 更新：**CLI 默认改为 [符号读取与编辑恢复](symbol-read-recovery.md) `symbol-recovery-v1`，默认最多 20 步、6 次编辑申请，可配置连续错误与重复动作停止条件。
以下初次生成加一次修正的说明保留为 `--workflow patch-v1` 旧协议；Python API 不传 workflow 时仍采用旧协议。
脚本响应现允许 1–100 个字符串；新协议可以包含 read_symbol/apply_patch/finish 动作。历史实验与旧 bundle 不变。

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

首次交付使用 scripted 验收；后续已补一次无思考本地真实推理，结果为目标未修复并回滚，见 [真实执行记录](local-issue-repair-20261019.md)。没有付费模型请求。
Ollama 请求不加载 `.env`、不读取云端 API Key、禁用代理环境和重定向；显式云模型名称被拒绝。
运行前应确认本机 Ollama 服务及模型由操作者管理；环回地址本身不证明服务值得信任。
无思考参数及完成状态按 [Ollama chat API](https://docs.ollama.com/api/chat) 处理。
截断、意外思考内容、工具调用或网络故障均停止，不将半份响应应用到源码。

## 使用方式

沿用 [README](../README_CN.md) 的 D 盘环境变量。先完成 [Issue 准备](github-issue-preparation.md)，
再使用**原始、未修改的可信配置**启动修复：

```powershell
# 仅在需要实际本地推理时手工运行；本轮验收不执行此命令。
python -B -m repairflow repair-issue --prepared .tmp/github-issues/click-3887 --config configs/issue-tasks/click-3887.json --output .tmp/issue-repairs/click-3887-001 --mode ollama --model qwen3.5:27b --workflow patch-v1
```

输出目录必须全新，不能与准备任务、配置目录或响应文件重叠。
Docker 和镜像条件在模型调用前检查；镜像内容 ID 必须与准备阶段一致。
即使环境设置了 `CORECODER_TEST_BACKEND=local`，该入口也不会退回宿主机测试。
若本机镜像标签无法查询，先修复镜像标签，或在可信配置中改用已核对的镜像 ID 并重新准备任务；不能静默换镜像。

旧协议的手工响应示例使用一至两个补丁 JSON 字符串；应显式加 `--workflow patch-v1`。新协议动作和次数见上方更新：

```json
[
  "{\"edits\":[{\"file\":\"src/pkg/__init__.py\",\"old\":\"    return x + 1\",\"new\":\"    return x + 2\"}]}"
]
```

以上补丁仅适用于自包含测试 fixture，不是 Click 修复。对准备任务使用相应候选响应：

```powershell
python -B -m repairflow repair-issue --prepared .tmp/my-prepared-issue --config .tmp/my-trusted-config/task.json --output .tmp/issue-repairs/scripted-001 --mode scripted --responses .tmp/my-responses.json --workflow patch-v1
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

## 模块绑定上下文与无进展诊断

新 Issue 入口默认保留原上下文策略。显式选择 `--context-policy module-bindings-v1` 时，先保留原检索的必选目标，再按顺序补充模块级导入、
公开测试调用的同模块顶层辅助函数、目标函数直接调用的同模块辅助函数，最后填充其他原始候选。
导入总量不超过 1,200 字符，全部证据仍最多 6,000 字符、5 段；可选内容超额时明确记录舍弃原因。
AST 只解析允许修改的源码，不执行模块、不增加读取范围。每段绑定实际路径、行范围与当前文件哈希。
这仍是静态上下文组织，不是模型自主搜索或完整语义依赖解析；同名调用也可能产生误匹配。

候选经过反馈后若净源码与基线完全一致，仍运行原公开检查，再输出 `status=no_progress`、
`no_progress_detected=true` 和 `no_net_source_change` 诊断。该分类只解释失败，不新增重试或放宽通过条件。
旧可信任务包与历史 50 项实验继续使用原策略。
该实验策略在第二轮单例中没有带来修复收益，因此不提升为默认。见 [第二轮记录](issue-context-round2-20261019.md)。

## 限制与证据

- 最多两次候选生成：初次加一次反馈；总 Token 记账上限 60,000，单次输出上限 32,768，上下文 65,536。
- 保留估算预检和返回用量记账；不是服务商计费硬上限。脚本响应无实测 Token，按预留额度保守记账。
- 阶段间检查 1,200 秒任务期限；本地请求不超过剩余时间和 480 秒，每个测试组沿用 Docker 的独立超时与资源限制。
- 沙箱故障不作为代码失败要求模型反复修改；参考修复和独立评分材料不会进入该流程。
- `provenance.json` 保存 Issue、commit、输入/配置哈希、镜像、预算、模式和新执行模块哈希。
- `initial/correction-*` 保存实际上下文、请求、响应、候选 diff 和公开检查日志；失败候选的诊断材料保留。
- `report.json` 区分脚本调用、本地真实模型调用、未知用量、公开测试和独立验收；`trace.jsonl` 保存阶段与调用事件。
- 原始准备任务不被写入；候选始终位于新任务目录。不自动 commit、push 或发布 PR。

已补一次新 Issue 的无思考本地真实推理，未修复目标；该单例不构成修复率评测，也不与历史 47/50 合并统计。

## 首次脚本验收（2026-10-19）

- 相关回归 **200 passed，0 failed，0 skipped**，含 32 项新单元/CLI/接口契约测试、2 项新真实 Docker 用例及既有沙箱/服务/审批回归。
- 两项新 Docker 用例使用自包含 fixture：有效候选进入待审查状态；错误候选经过最多一次修正后回滚。均无模型请求。
- 复用已准备的真实 Click #3887，手工指定一份能应用但不改变缺陷行为的候选；实际 Docker 验证确认目标仍失败、3 项正常行为检查通过，最终拒绝交付、恢复源码并清空最终 diff。
- 上述 Click 用例是负向执行验收，不代表模型尝试修复失败，也不是新增模型修复成绩；初次候选 diff 和诊断材料仍保留。
- 本机已有沙箱镜像标签查询再次失效；将同一已核对内容 ID 重新赋予原标签后，查询恢复。未构建或拉取镜像，根因仍未确定；相关回归使用固定镜像 ID。
- 实际模型调用为零；原始 Issue 准备数据、历史实验和 8001 服务不改动，全部新增状态与报告位于 D 盘。

结构化结果见 [验收摘要](prepared-issue-repair-acceptance.json)。本地原始产物位于 `.tmp/issue-repair-acceptance-20261019/`。
