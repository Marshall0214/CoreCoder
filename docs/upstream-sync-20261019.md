# 上游同步与 README 整理（2026-10-19）

## 同步范围

通过公开 GitHub fork 元数据确认上游为 [he-yufeng/CoreCoder](https://github.com/he-yufeng/CoreCoder)，
添加本地 `upstream` remote，并合并其 main。

- 本地合并前：`4c93446`，Issue 准备阶段已提交。
- 共同基点：`745ff657a465b606f4eba1133c645721ebce95de`。
- 上游目标：`13b18dac85a1a695581091e98d88d1486faf7b22`，比共同基点新增 20 个提交。
- 核心包从 0.6.0 更新为上游 0.8.0；这不代表完整修复系统已独立打包发布。
- 使用 `git merge --no-commit --no-ff upstream/main`，解决冲突并验证；未自动提交或推送。

## 纳入的上游能力

| 能力 | 变化 |
| --- | --- |
| Windows Shell | 通过 Git Bash 执行 POSIX 命令，处理 Windows 盘符路径 |
| 撤销记录 | checkpoints 可跨进程重启保留 |
| 用户授权 | 交互 CLI 的 always-allow 可持久化；非交互模式仍默认拒绝修改 |
| MCP | `/mcp` 状态查看及手动 reconnect |
| 用量价格 | 本地 pricing.json 覆盖内置估算价格 |
| 会话恢复 | 损坏 UTF-8 会话不导致恢复过程崩溃 |
| 测试与导读 | REPL、Shell、持久化、MCP 新用例及源码导读修订 |

上游的真实模型冒烟测试保持显式 opt-in，本轮设置 `CORECODER_LIVE_SMOKE` 为空，禁止其调用模型。

## 本地兼容处理

- 保留 `fetch_url` 及其现有只读权限，不因上游权限模块变化丢失。
- 保留服务、MCP Server、LangGraph 的可选依赖及本地仓库元数据。
- 保留 D 盘 pytest 临时目录及现有并行工作区测试。
- 新增 `CORECODER_HOME`：启动前可把撤销、授权、会话、历史及配置放入 D 盘；不设置时保留上游默认路径。
- 服务工作进程显式使用本任务的状态目录，避免新的持久化栈跨任务写入用户目录。
- 修复现有 fetch 工具的 ClassVar/lint 标注，以及少量测试的导入/字典字面量 lint；未改其执行语义。
- 原始 Bash 仍不是 Docker 沙箱；上游更新不扩大新修复流程的执行权限。
- 历史目录/投影单元测试使用显式冻结版本 fixture，另增加版本不匹配必须拒绝的测试；冻结适配器的真实版本校验未放宽。
- 仅使用标准库的历史测试 fixture 改用当前测试解释器，避免依赖已失效的临时虚拟环境；不改变正式实验的解释器配置。

README 中英文均调整为当前扩展项目入口，明确两条尚未连通的流程：
公开 Issue 的准备，以及可信任务包的修复。历史成绩、离线回放和单测数量分开说明。
原始导读保留在 article/，作者署名和 MIT 许可证保留。

## 实验与兼容性边界

`docs/experiments/`、`evals/`、任务配置和修复/沙箱模块未因合并改写；
历史评测产物不重算、不覆盖，47/50 继续属于原实现版本及旧协议。
底层 LLM、Shell、会话代码已变化，今后的新实验必须保存新实现版本，不能把旧结果当作合并后重新测得。
源码导读中指向当前文件的精确行数按合并后的代码校正，保留上游的行数校验测试。

## 验证

- 核心兼容用例：132 项通过。
- 最终全仓库回归：**1667 passed、3 skipped、0 failed**，耗时约 378 秒，包含 **9 项真实 Docker 测试**。
- 跳过：两项符号链接用例受本机 Windows 权限限制；一项真实模型冒烟测试按要求禁用。
- Ruff：`corecoder tests service repairflow sandbox` 全部通过；中英文 README 各 15 个本地链接有效。
- 全仓库回归结果见 [同步验收摘要](upstream-sync-20261019.json)。原始 JUnit 报告保存在本地 `.tmp/upstream-sync-20261019/regression-final.xml`，不提交临时产物。
- 验证过程中不使用模型 API 或 thinking 推理，不操作现有 8001 服务。
- 状态、缓存、临时目录及报告位于 D 盘；真实 Docker 用例使用既有受限容器策略。

首轮全量回归有 19 项失败：11 项涉及旧解释器或冻结引擎的单元测试 fixture，8 项为镜像标签预检失败。
前者通过上述测试环境适配处理；Docker 单独复测 9 项通过。
最终全量运行通过 `CORECODER_SANDBOX_IMAGE` 固定本地镜像内容 ID：
`sha256:b26ab495fcf2ae0473cd4a9a7430700697e9041cdbe3fd4c6d2238274319b219`。
镜像标签预检曾失败的原因尚未确定；未因此改写沙箱逻辑或放宽隔离策略。
固定内容 ID 的通过结果不证明标签查询问题已根治。

## 提交说明

这是一次待人工提交的上游合并。确认 `git diff --name-only --diff-filter=U` 无输出后，
按常规检查暂存区并提交；不要把历史实验数据重新生成后混入本次上游同步。
