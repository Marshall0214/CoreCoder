# 真实跨文件缺陷准入 v1

## 目的与本次交付

上一步三个 Click 案例都是单源码文件修复。本次补充一个官方修复涉及两个行为源码文件的真实历史缺陷，并验证单文件部分修复与完整修复的区别。尚未执行 Agent 修复，也未冻结开发/留出集。

扩展 `evals/real_admission.py`：可选择候选清单及独立测试解释器；对标记的案例，从原始源码分别只覆盖一个官方修复文件进行诊断。原始、修复后、部分修复源码和日志分别保存，源码和检查在执行前后校验摘要。

## 候选来源与行为

候选：`click-flag-envvar`。来源为 [Click 问题 2952](https://github.com/pallets/click/issues/2952) 与 [官方 PR 2956](https://github.com/pallets/click/pull/2956)，2025-07-01 合并；BSD-3-Clause，完整快照保留 LICENSE.txt。

- 原始提交：`5c1239b0116b66492cdd0848144ab3c78a04495a`。
- 修复提交：`565f36d5bc4a15d304337b749e113fb4477b1843`，验证其首父提交与原始提交一致。
- 官方行为源码修改：`src/click/core.py` 和 `src/click/types.py`，同时涉及选项取值与布尔规范化。
- 公开行为：环境变量中的 false/0/off 不应激活非布尔 flag；true 类值或与 flag_value 精确相同的值应激活；布尔选项的纯空白值表示 false。保持命令行显式激活和普通参数转换。

自主编写 3 个 Target 测试方法（含多值子测试）以及 3 个 Controls 方法。通过公开 CLI 行为检查，不直接断言内部实现或调用新加的私有辅助函数。

已查看公开修复，所以该案例仅用于开发。官方补丁覆盖多个边界，本次检查只覆盖所列行为，未执行完整上游测试。候选清单为 `evals/real_defects/crossfile-candidates.json`，与先前单文件清单分开保存。

筛选中排除 PR 2800 作为跨文件修复候选：虽然它修改两个源码文件，其中 core.py 的改动只涉及文档说明。源码文件数量不能直接代表跨文件行为修复需求。

## 实测结果

2026-10-05，Windows / Python 3.11.16，在 `.tmp/real-defects/click-stdlib-env` 新建 venv，未启用 system-site-packages，未安装 pip 或第三方包。环境记录确认 colorama、typing_extensions 均未安装。显式导入每个固定快照的 src，并验证实际 Click 导入路径。

| 源码组合 | Target | Controls | 结论 |
| --- | --- | --- | --- |
| 原始版本 | 失败 | 通过 | 缺陷可复现 |
| 完整官方修复 | 通过 | 通过 | 通过准入 |
| 原始版本 + 仅官方 core.py | 失败 | 失败 | 缺少配套类型能力，出现执行异常 |
| 原始版本 + 仅官方 types.py | 失败 | 通过 | 选项取值链路仍有缺陷，目标行为未修复 |

部分 core.py 修复在 CliRunner 内捕获异常，再导致 exit_code 断言失败；日志保留异常信息。此类部分修复失败是诊断结果，不等同于成功复现原始业务缺陷。只有原始版本的业务断言失败及完整修复通过决定准入。

证据保存于 `.tmp/real-defects/crossfile-admission-v2/admission.json`、`environment.json` 及候选目录中的源码、归档、提交元数据和日志。报告记录父进程与测试解释器环境、许可证/源码/检查摘要及每组执行结果。之前 v1 为初次通过记录，v2 对应最终版本。

代码验收：准入工具测试 12 passed；全量回归 494 passed、1 skipped；新增及修改文件 Ruff 检查通过。原有三个单文件案例重新准入均通过，证据为 `.tmp/real-defects/admission-v4/admission.json`。

这说明所选官方补丁中的两个文件需要配套应用，不证明任何替代实现都必须修改两个文件，也不能据此宣称 Agent 或检索收益。单案例不足以支撑总体成功率。

## 复跑

在仓库根目录、corecoder 环境执行。环境目录和结果目录应使用新路径，保留先前证据：

```powershell
python -m venv --without-pip .tmp/real-defects/click-stdlib-env-reproduction
python -m evals.real_admission --catalog evals/real_defects/crossfile-candidates.json --python .tmp/real-defects/click-stdlib-env-reproduction/Scripts/python.exe --output .tmp/real-defects/crossfile-admission-reproduction
python -m pytest tests/test_real_admission.py -q
python -m pytest tests -q
```

预期候选输出 admitted、进程退出码 0；两种部分修复不能通过全部检查。下载阶段需要网络，检查使用本地源码。独立 venv 用于依赖隔离，并非操作系统沙箱或跨平台容器验收。

## 后续

将已准入真实源码接入 Agent 执行器：准备独立工作区、限制可写源码范围、保留上游许可和来源；在父进程持有参考修复及独立检查，评分时复制到干净源码中验证。开发任务只用于协议调试，留出任务另行筛选并冻结。随后开展固定模型、工具与预算下的检索及上下文对照。
