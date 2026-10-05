# 真实历史缺陷准入 v1

## 本次做了什么

把评测任务来源从人为构造的样例扩展到真实开源历史缺陷。先验证任务本身可靠，再让 Agent 尝试修复。本次没有调用模型，没有测量 Agent 修复成功率。

新增 `evals/real_admission.py`、固定提交的候选清单及自主编写的行为检查。下载完整上游源码快照；用同一组检查验证缺陷前版本与官方修复后版本，并保留许可证、提交元数据、源码与检查摘要、导入路径、环境版本和执行日志。

## 候选与来源

| 候选 | 用户可观察的问题 | 原始提交 → 修复提交 | 上游来源 |
| --- | --- | --- | --- |
| click-help-eagerness | 帮助选项先出现时应显示帮助，不执行后面的 eager 回调 | `273fb90106726daa16e1033eca0d677de76345eb` → `70c673d37eb91ba42a129be9037caf3ebed62f3e` | [PR 2811](https://github.com/pallets/click/pull/2811) |
| click-flag-default-map | 双向布尔选项的帮助应显示 default_map 覆盖后的默认值 | `5b1624bf09947d6f10eaffd63d6fb737dfe7656a` → `bc16dbf788861266177661b576291a1b264fb5de` | [问题 2632](https://github.com/pallets/click/issues/2632)、[PR 2730](https://github.com/pallets/click/pull/2730) |
| click-resource-exception | 注册的上下文管理器应收到异常信息，且可抑制异常 | `16fe802a3f96c4c8fa3cd382f1a7577fda0c5321` → `36deba8a95a2585de1a2aa4475b7f054f52830ac` | [问题 2447](https://github.com/pallets/click/issues/2447)、[PR 3058](https://github.com/pallets/click/pull/3058) |

三项均为 BSD-3-Clause；下载快照保留完整 LICENSE.txt。核对修复提交的首父提交与候选一致，并核对实际源码改动范围。三项都只修改 `src/click/core.py`，属于真实单源码文件缺陷，不能算跨文件修复评测。问题描述及检查均为开发资料，已查看公开修复，不能再作为留出集。

## 准入规则与结果

Target 检查复现目标缺陷，Controls 检查相关正常行为。仅当原始版本出现目标断言失败、无执行错误或超时且 Controls 通过，同时修复后两组都通过，才接受任务。零测试、导入失败、环境错误均不算成功复现。

2026-10-05 在 Windows、Python 3.11.16 / corecoder conda 环境实测：

| 候选 | 原始 Target | 原始 Controls | 修复后 Target / Controls | 准入 |
| --- | --- | --- | --- | --- |
| click-help-eagerness | 1 项目标检查失败 | 1 项通过 | 1 / 1 项通过 | 通过 |
| click-flag-default-map | 1 项目标检查失败 | 1 项通过 | 1 / 1 项通过 | 通过 |
| click-resource-exception | 2 项目标检查失败 | 1 项通过 | 2 / 1 项通过 | 通过 |

最终证据：`.tmp/real-defects/admission-v3/admission.json`，以及各候选的 before/after 快照、归档、许可证和日志。早期 v1 许可证空格匹配导致拒绝，v2 已通过；v3 保存最终实现版本的证据，不覆盖旧记录。

代码验收：新增准入工具测试 10 passed；全量回归 492 passed、1 skipped；新增文件 Ruff 检查通过。

子进程以 `python -I -B` 执行，显式导入固定快照的 src 并检查实际导入路径；日志位于快照外，执行前后检查源码与测试摘要。子进程不继承模型密钥。没有安装或升级共享环境依赖；记录 colorama 0.4.6、typing_extensions 4.16.0。此措施用于导入隔离和可追溯，并非操作系统沙箱或完全锁定的容器环境。下载阶段需要联网，测试本身使用本地源码。

Controls 是小范围行为检查，没有运行上游完整测试套件。本次准入工具尚未接入 `python -m evals --mode live`，也没有冻结开发/留出集或改变现有评测默认策略。

## 复跑

在仓库根目录、corecoder 环境执行，output 必须是一个新目录：

```powershell
python -m pytest tests/test_real_admission.py -q
python -m evals.real_admission --output .tmp/real-defects/admission-reproduction
python -m pytest tests -q
```

准入结果应为三项 admitted、进程退出码 0。原始源码发生目标断言失败是预期现象，不需要修复下载的 before 快照。归档拒绝路径穿越、符号链接、Windows 大小写重名及过大文件；原始归档只保存在忽略的 .tmp 中。

## 下一步

筛选需要跨源码文件定位或修改的真实任务，准备独立依赖环境和真实任务执行适配；确认原始失败、参考修复与正常行为回归后，冻结开发/留出划分。随后在固定模型、工具与预算下比较检索和上下文策略。这三个 Click 案例保留为开发和真实来源冒烟检查，不用于宣称检索收益。
