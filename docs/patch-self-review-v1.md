# 补丁自审：30 项开发集完整对照

在类范围检索基础上，共享同一次首轮回答；候选再审查一次 Issue、原始源码和首轮补丁。
不读取私有测试或参考修复，最终评分在两个候选都生成后执行。

| 指标 | 单次修复 | 一次自审 |
|---|---:|---:|
| 独立通过 | 14/30 | 14/30 |
| Controls 通过 | 29/30 | 29/30 |
| 策略调用数 | 30 | 60 |
| Token | 83110 | 170455 |
| 生成阶段秒 | 316.2264 | 376.6222 |

实际新增调用总数：60，两组共享首轮，不能相加为两个独立实验的调用数。
生成阶段计时含证据检查、请求和候选复制，不含独立评分或父进程开销。

自审选择分布：{"kept_initial": 30}。

## 收益与回归

新增成功：无。
丢失成功：无。
新增 Controls 失败：无。
事前门槛结果：False（净新增至少 2 项，且无新增 Controls 回归）。

## 可观察失败分类

| 类别 | 单次修复 | 一次自审 |
|---|---:|---:|
| control_regression | 1 | 1 |
| passed | 14 | 14 |
| target_failed | 15 | 15 |

## 决策与边界

未达到开发门槛，停止扩展自审策略，不跑留出、不替换默认流程。
额外一次调用和补丁上下文同时改变；不能把差异单独归因于推理能力或检索。
30 项为已查看的开发任务，每项只运行一次；结果不能宣称通用收益或优于 Claude/Codex。
Target 未通过只是观察结果，不能直接归因为定位错误或模型理解不足。

## 复现

```powershell
python -m docs.experiments.patch_self_review_v1 --admission .tmp/real-defects/expanded-admission-v2-final/admission.json --output .tmp/real-defects/patch-self-review-rerun
python -m docs.experiments.patch_self_review_report_v1 --input .tmp/real-defects/patch-self-review-rerun/experiment.json --output .tmp/real-defects/patch-self-review-rerun/report
```

需要已有冻结任务快照、指定测试解释器和身份一致的本地 Ollama。输出目录必须不存在。

## 软件验收与产物

新增专项：12 passed；Windows 全量：1,251 passed、4 skipped（165.87 秒）。
跳过包含两个缺少 langgraph.checkpoint.sqlite 的可选审批模块，以及 Windows 符号链接权限相关测试；不把跳过计为通过。
新增代码 Ruff 与 git diff --check 通过；本轮未重跑 Docker/Linux 或真实 HTTP。

正式输入、两次请求、模型原文、补丁与独立评分日志位于 `.tmp/real-defects/patch-self-review-v1/`，被 Git 忽略；机器摘要见 [结果摘要](patch-self-review-v1.json)。
执行器见 [代码](experiments/patch_self_review_v1.py)，报告生成器见 [代码](experiments/patch_self_review_report_v1.py)。

## 下一项核心工作

不再单纯增加无执行证据的模型自审。优先扩展公开缺陷复现检查和正常行为回归检查，让第二次修复依据真实执行失败，而不是自身判断。
公开检查应从 Issue 和公开 API 契约独立构造，并在模型运行前冻结；现有私有 Target/Controls 保持独立最终评分，不能直接拿来提示模型。
已有两项公开反馈试验仅证明 usage-empty 的局部收益，不能推定对 30 项任务有效。下一轮先完成开发任务的公开检查准入，再运行统一流程对照。
