# GitHub Issue 只读导入与任务准备

## 当前能力

输入公开 Issue URL 和管理员维护的固定版本配置，获取问题描述与源码，在 Docker 中验证缺陷能否复现，输出准备任务及证据。
**不调用模型，不生成补丁，不向 GitHub 创建评论、分支或 PR。**

```text
Issue URL + 可信配置
→ Docker/镜像预检
→ GET Issue 标题正文 → GET 固定 commit 元数据 → 下载该 commit 的源码 ZIP
→ 校验并解包 → 复制可信测试
→ 独立容器执行 Reproduce 和 Preserve
→ task.json + report.json + 测试日志
```

仅支持公开 github.com 仓库，不使用 GitHub Token、Cookie 或本地模型密钥。
请求地址由校验后的仓库名和完整 SHA 构造；不跟随重定向，不请求评论、timeline 或关联 PR。
遵循 [GitHub Issue REST API](https://docs.github.com/en/rest/issues/issues#get-an-issue)，拒绝返回 pull_request 字段的对象。
正文可能被上游编辑，保存获取时间与更新时间；不宣称获得了历史原始正文，也不会执行其中的命令。

## 运行

在仓库根目录 PowerShell 中使用 corecoder 环境，先按 [沙箱说明](execution-sandbox.md) 准备本地 Docker 镜像：

```powershell
$env:DOCKER_CONTEXT='desktop-linux'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
python -B -m repairflow import-issue --url https://github.com/pallets/click/issues/3887 --config configs/issue-tasks/click-3887.json --output .tmp/github-issues/click-3887
```

重复运行应指定新输出目录，不覆盖历史证据。源码下载保存为工作区副本，不执行 git hooks、setup.py、构建后端或自动安装依赖。
CLI 使用显式可信配置路径；尚未开放 HTTP 导入接口。未来 API 必须由服务端配置目录选择任务，不能允许请求指定任意配置路径或测试脚本。

## 可信配置

示例：[Click #3887 配置](../configs/issue-tasks/click-3887.json)。

| 字段 | 约束 |
| --- | --- |
| repo / issue_number | 必须与输入 URL 完全一致 |
| base_commit | 完整 40 位 SHA，不接受浮动分支或标签 |
| image | 管理员准备的本地镜像；执行前固定实际 image ID |
| package / source_root | 当前支持 Python 包，必须存在指定入口 |
| allowed_files | 显式存在的 Python 文件；供后续修复阶段使用 |
| harness | 配置目录内的可信测试目录，含 test_admission.py |
| license_file / license_id | 人工审查的许可证声明及仓库许可文件，记录文件哈希 |

配置本身是管理员信任输入，并非对任意用户提供安全授权。哈希用于完整性核对，不代替身份认证或签名。
当前镜像适用于无额外依赖的验收；其他仓库需先建立受控依赖镜像，不能运行时从 Issue 内容拼接安装命令。

## 准备成功标准

- Reproduce：测试数量大于零，发生断言失败，退出码为 1，没有执行错误、跳过或预期失败。
- Preserve：正常行为测试全部通过且无跳过。
- 测试前后源码和测试材料哈希不变。

同时满足才返回 `ready_for_repair`。目标测试通过记为 `not_reproduced`；正常行为失败记为 `baseline_regression`；
零测试、执行错误等不能作为有效复现；Docker 和网络故障分别保留失败阶段和错误类型。
Docker 或镜像预检失败时，不下载源码，也不自动退回宿主机执行。

`ready_for_repair` **不是已修复或独立验收通过**。准备产物不是现有 `bundle.json`：
没有把公开测试复制成所谓隐藏评分器，不能直接传入旧 `repairflow run --bundle`。
后续接入需要明确“仅通过公开测试”和“通过独立验收”的不同交付状态。

## 产物

```text
issue.json             # 经过字段筛选的公开标题、正文和时间
source/                # 固定版本源码，保留许可证
public/                # 本次可信测试快照
admission/             # 每组执行器、结果、日志及容器诊断
task.json              # 问题描述、版本、修改范围、输入哈希和准备状态
report.json            # 不重复正文的准备报告
```

任务记录 Issue、配置、归档、源码、测试、许可文件哈希，以及实际请求 URL 和镜像 ID。
后续阶段可调用 `load_prepared` 检查源码、测试和问题快照是否变化。失败任务不允许被该接口当作已准备任务加载。

ZIP 下载最多 32 MB，展开最多 64 MB，单文件最多 1 MB，成员数最多 20,000。
解包前检查路径穿越、符号链接/特殊文件、Windows 保留名称、大小写别名和文件/目录冲突。
这些限制有意排除大型仓库，后续扩展需明确调整策略，不静默放宽。

## 真实开发验收（2026-10-19）

- 来源：[Click #3887：ANSI escape codes break style()](https://github.com/pallets/click/issues/3887)。
- 版本：Click 8.1.8，commit `934813e4d421071a1b3db3973c02fe2721359a6e`。
- 根据报告者示例构造可信测试，检查预着色红色输入是否被显式蓝色覆盖；这是对报告者预期的解释，不是上游批准的修复规格。
- 原始版本 Reproduce：1 项断言失败、0 项错误；Preserve：3 项通过；准备结果为 `ready_for_repair`。
- 仅 3 次公开 GET 请求；无参考补丁、评论或关联 PR 请求；新增模型调用为 0，未使用 thinking。
- 该例属于开发验收，不并入原来的 50 项任务，不构成新的修复率或留出集成绩。

原始证据位于 `.tmp/github-issue-acceptance-20261019/click-3887-v2/`。
最终相关回归、输入摘要与证据哈希见 [验收摘要](github-issue-preparation-acceptance.json)。
本轮 **197 项相关回归通过，无失败或跳过**，包含 34 项新增 Issue 准备测试及 9 项既有真实 Docker 测试；Ruff 通过。

## 下一步

为准备任务增加服务端受信目录与审批入口，明确缺少独立评分材料时的报告语义，再接入候选修复。
模型调用继续保持关闭；后续启用时按当前要求先关闭 thinking，与旧高思考实验分开记录。
