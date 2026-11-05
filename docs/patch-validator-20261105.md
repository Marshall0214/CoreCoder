# 补丁验证器：实现与验收（2026-11-05）

本轮把 [agg1 失败复盘](harness2-agg1-failure-20261104.md)中的两类错误变成可执行检查：未定义符号由静态检查发现，重复输出由公开行为测试发现。验证器由控制端管理，Harness² 无权修改。已完成独立入口和真实 Docker 验收，**尚未接入 Agent 自动反馈修正循环**。

运行制品仍保留在 `.tmp/patch-validator-20261104`；本页及归档日期是交付日期，不重命名历史目录。可提交的 [证据清单](patch-validator-20261105.json)对应目录 `patch_validator_20261105/`。

## 检查流程

```text
基线源码导出 + 候选源码导出 + 控制端指定的可写路径
  → Diff / 路径 / 空补丁检查
  → 编译语法检查（不执行源码）
  → Ruff 基线与候选对照 → 区分遗留位置与新增位置
  → Docker 公开 Reproduce / Preserve 检查
  → validation/report.json

控制端另行运行 Target / Controls → 独立评分制品
```

- 仅支持项目工作区内的独立导出目录；限制修改既有、指定的非测试 Python 文件，拒绝链接、越界、新增文件和删除文件。输入不得与输出混放。
- Ruff 0.16.9 使用隔离配置、忽略 `noqa`、禁用修复和缓存，目标版本 `py311`，规则为 `F821/F822/F823`。它检查未定义名称、未定义导出及局部变量先使用后赋值，**不等于完整 API 或类型检查**。
- 通过未改动行映射关联基线诊断。agg1 保留了原始第 918 行的问题（候选第 923 行），又在第 908 行新增同名问题；不会因为基线已有 `iteritems` 就豁免第二处。移动的代码可能被记作旧位置消失、新位置出现，不能据此认定问题修好。
- AST 重复循环只产生非阻断审查提示；互斥分支可能合法重复。是否造成重复输出由执行测试判断。
- 公开检查复用现有 Docker runner：无网络、只读挂载和根文件系统、1 CPU、1 GiB 内存、64 PID、输出上限 1 MiB。镜像 ID 固定为 `sha256:b26ab495fcf2ae0473cd4a9a7430700697e9041cdbe3fd4c6d2238274319b219`。不回退到宿主机执行候选源码。
- 两组公开检查均须实际运行非零用例，且无失败、错误、跳过或预期失败。缺少检查器、Docker 不可用或结果异常时不批准补丁。

`validated / accepted=true` 仅表示通过配置的公开检查和静态规则；`rejected / false` 表示未满足准入条件；`blocked / false` 表示验证受阻。未指定公开测试时返回 `static_only / accepted=null`，静态检查不能签发修复成功结论。正常返回这四种状态时 CLI 退出码分别为 0、1、2、2；非法参数、路径或重复输出目录可直接报错退出。

## 四份制品的实际结果

| 制品 | 候选静态问题 | 公开复现（2 项） | 公开保持性（3 项） | 准入 |
| --- | --- | --- | --- | --- |
| 原始未改源码 | 1 处遗留 | 0/2，NameError | 3/3 | 拒绝，且无补丁 |
| 保存的 Agent agg1 | 1 处遗留 + 1 处新增 | 0/2，NameError | 3/3 | 拒绝 |
| 人工诊断：仅修正名称 | 0 | 0/2，重复输出 | 3/3 | 拒绝 |
| 人工诊断：修正名称并去掉多余循环 | 0 | 2/2 | 3/3 | 通过 |

后验独立评分与上述诊断一致：前三份 Target 均 0/1，最后一份 1/1；四份 Controls 均 1/1。独立结果保存到各制品的 `independent/`，不用于验证器准入、模型反馈或 Harness² 策略选择。

公开测试来自已知开发任务的 `join` 契约示例，覆盖未匹配左行只输出一次、空右序列、内连接多对多、右外连接和空左序列。作者已看过该任务，**不属于未见任务验证**。两个诊断补丁为人工构造，不计作 Agent 修复成功。

本次共执行 16 个沙箱检查组，包含公开测试 20 次、独立测试 8 次；新增模型调用 **0**。四份制品用于验证机制，不能估计整体错误发现率、误报率或修复率。原自有 Agent **21/50** 基线未变。

## 代码与复现

- `repairflow/patch_validator.py`：控制端验证器和独立 CLI。
- `repairflow/validation_checks/toolz_join/test_admission.py`：2 项 Reproduce、3 项 Preserve。
- `evals/patch_validator_admission.py`：从保存的 agg1 重建四份制品，分别验证、独立评分并校验历史证据。
- `deploy/langfuse/patch_validation.py`：可选发布公开验证摘要，字段白名单排除独立评分。
- `tests/test_patch_validator.py`：12 项边界与语义测试。

在仓库根目录、已激活的 `corecoder` 环境执行。需要已安装 Ruff、现有评分镜像及历史实验输入；驱动器不是可脱离这些输入运行的任务下载器。所有新目录使用 D 盘，输出必须不存在：

```powershell
$env:PYTHONPATH = 'D:\project_other\CoreCoder'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHON_DOTENV_DISABLED = '1'
$env:TEMP = 'D:\project_other\CoreCoder\.tmp'
$env:TMP = $env:TEMP
python -B -m evals.patch_validator_admission --output .tmp/patch-validator-recheck-20261105
```

此命令实际运行 Docker 检查，但不调用模型。普通调用方也可用独立 CLI 检查已准备的导出目录：

```powershell
python -B -m repairflow.patch_validator `
  --baseline .tmp/patch-validator-20261104/agent_agg1/validation/baseline `
  --candidate .tmp/patch-validator-20261104/agent_agg1/source `
  --allowed toolz/itertoolz.py `
  --public-checks repairflow/validation_checks/toolz_join `
  --package toolz --output .tmp/patch-validator-single-recheck-20261105
```

agg1 应返回 `rejected` 和退出码 1，这是预期拒绝结果。仅做静态检查可省略 `--public-checks/--package`，此时不能得到准入成功。

## 验收与可观测性

相关回归已完成：**71 passed、1 skipped**；跳过项属于已有 Python 3.12 控制器测试，本次运行环境为 Python 3.11。五份新增代码 Ruff 检查通过。未重新运行全仓库测试或 50 项模型评测。

[Langfuse 验证轨迹](http://127.0.0.1:3300/project/corecoder-issues/traces/309877b62f9f4bc26e452cb44147650b)已回读核对：5 个普通 Span、0 个 Generation；实际 Agent 制品关联其原推理 Trace，不伪造新模型运行。发布摘要不包含独立评分，服务器回读结果与公开输出一致。Langfuse 记录证据，准入判断仍由验证器执行。

归档包含协议、结果、Diff、静态诊断、公开/独立检查日志、源码快照及逐文件 SHA256；不包含凭据、依赖或镜像。历史自主实验、失败复盘和本地 50 项基线的 505 份证据已核验保留。

## 下一阶段边界

接下来可建立经验准入协议，或设计仅使用公开验证反馈的一次受控修正对照。本轮均未实现，不继续扩张 Harness² 权限。需分别回答“检查能否发现错误”和“Agent 能否利用反馈修好”，通过公开检查也不能代替独立评分或证明经验可跨任务复用。
