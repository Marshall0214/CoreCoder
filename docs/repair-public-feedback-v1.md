# 公开检查与一次反馈修复 v1

本轮把“生成补丁后直接评分”扩展为可选的“公开检查失败后再修一次”。收益出现在 usage-empty：单次修复 0/3，反馈修复 3/3；none-salt 两组均 0/3。反馈组实际 Token 为单次组的 2.57 倍，保持为两任务实验适配器，没有替换默认方案。

## 做了什么

- 从公开需求逐条摘录契约来源，人工编写 Click 4 项、ItsDangerous 7 项检查。示例输入由开发者选择，默认盐值依据原始公开 API；不是模型自动生成测试。
- 在模型实验前冻结检查代码与来源哈希，验证原始缺陷和 12 个历史失败补丁均触发断言失败，两个人工正例分别通过 4/4、7/7。正例仅用于离线验证，不给模型，也不使用上游参考补丁构造预期。
- 候选代码在独立副本执行公开检查，校验源码来源与前后快照。原始代码和候选代码都出现有效断言失败时，才允许一次反馈；超时、执行错误、零测试或无效补丁不会触发反馈。
- 第二次输入包含冻结的公开测试、公开失败输出，以及按原路径/符号重新提取的候选函数。私有 Target/Controls 始终在父进程独立评分，不进入模型输入。
- 两次调用共用一个预算对象，上限仍是每任务 15,000 Token；最多一次反馈，没有第三次重试。预算停止时保留第一阶段记录。

离线正例证明这些检查能区分已知样例，不代表覆盖完整契约。源码见 `docs/experiments/repair_public_checks_v1.py`、`repair_public_feedback_worker_v1.py` 和 `public_checks_v1/`。

## 对照与结果

固定 Ollama qwen3.5:27b、温度 0、reasoning none、Context 16,000、单次输出上限 2,048、完整函数 BM25 证据和唯一原文替换协议。模型及引擎哈希、协议和逐次结果见 [机器摘要](repair-public-feedback-v1.json)。两个已分析失败任务各重复三轮；六对首次请求的 Prompt 哈希一致。

| 任务 | 单次修复 | 一次公开反馈修复 |
| --- | --- | --- |
| click-usage-empty | 0/3 | 3/3 |
| itsdangerous-none-salt | 0/3 | 0/3 |
| 合计 | 0/6 | 3/6 |
| 实际模型调用 | 6 | 12 |
| 实际 Token | 16,056 | 41,316 |

usage-empty 的反馈补丁通过公开检查和独立 Target/Controls。none-salt 的反馈补丁通过 6/7 项公开检查，但错误地把 Serializer 的显式 None 回退为 Serializer 默认盐值；需求要求此时采用 Signer 默认盐值。该行为仍不通过独立评分，不能按部分测试通过计为修复成功。

这是完整工作流比较：反馈组增加了测试信息和一次调用机会。相同预算上限不等于相同实际成本；不能将收益单独归因于检索或 Prompt。两项任务来自已查看的失败案例，重复三轮不增加不同缺陷数。

另对 echo-empty-bytes、style-color-validation、future-age、malformed-time 各运行一次全新单次修复，均通过（4/4）。它们使用原有单次执行器，未启用公开反馈；这四次回归不能与上表合并成统一成功率。本轮共 22 次新模型调用。

## 验收与复跑

相关回归 42 passed；最终 Windows 全量 919 passed、2 skipped（150.14 秒）；新增 Python 文件 Ruff 通过。本轮没有重跑 Linux、容器和 HTTP 故障验收。

所有新产物在 D 盘；使用既有 Conda 环境，没有安装依赖或操作已有用户服务。先设置环境：

```powershell
$env:TEMP='D:\project_other\CoreCoder\.tmp\python-temp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONPATH='D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
```

在已激活的 corecoder 环境中，可复跑测试或独立离线检查（输出目录必须未存在）：

```powershell
python -B -m pytest tests/test_repair_public_feedback.py -q -p no:cacheprovider --basetemp .tmp/public-feedback-tests-user
python -B -m docs.experiments.repair_public_checks_v1 --output .tmp/real-defects/repair-public-checks-user
```

真实对照默认读取既有 `.tmp/real-defects/repair-public-checks-audit-v1-certified/audit.json`，并核对检查代码和原始源码哈希。上面的独立离线检查不会自动替换该证书。还需要冻结的仓库快照、历史失败响应、隔离评分环境和指定 Ollama 模型；这些原始材料在被忽略的 `.tmp/`，仅 clone 不足以重建本轮实验。

```powershell
python -B -m docs.experiments.repair_public_feedback_v1 --output .tmp/real-defects/repair-public-feedback-user --repeat 3
python -B -m docs.experiments.repair_public_regression_v1 --output .tmp/real-defects/repair-public-regression-user --repeat 1
```

当前原始报告分别位于 `.tmp/real-defects/repair-public-feedback-v1/experiment.json` 和 `.tmp/real-defects/repair-public-regression-v1/experiment.json`。没有修改历史评分、模型适配器或默认服务流程。

下一步应聚焦 none-salt 中“参数省略”与“显式 None”的语义关系，检查所需调用链上下文；公开检查已经能指出错误，不应直接增加重试次数来掩盖它。
