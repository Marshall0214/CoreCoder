# 30 项真实缺陷：固定基线完整评测

从历史 13 项扩充至 **30 个不同缺陷、5 个仓库**，新增 17 项，全部通过修复前/上游修复后的准入检查。固定模型和统一单次补丁协议，完整运行全部 30 项，独立修复通过 **12/30（40%）**。这是新的宽任务集基线，不是对以前六项、两轮反馈的 5/6 的直接复测。

任务、提交及来源见 [固定任务清单](expanded-suite-v1.json)，评分和用量见 [机器摘要](expanded-baseline-v1.json)。

## 样例覆盖和划分

| 仓库 | 任务数 | 独立修复通过 |
| --- | ---: | ---: |
| pallets/click | 10 | 3/10 |
| pallets/itsdangerous | 3 | 2/3 |
| pytoolz/toolz | 4 | 2/4 |
| mahmoud/boltons | 4 | 1/4 |
| more-itertools/more-itertools | 9 | 4/9 |

新增覆盖空迭代器、累计运算、连接未匹配项、空索引、常数退避、零次切分、bytes 分块、集合重建、假值异常、批次数量限制、零缓存 peek、组合索引、异常传播和数值范围切片等行为。它们来自真实固定上游修复，不是人为往正常源码注入错误。多数为单文件修复，不能把 30 项都称为跨文件任务。

推理前冻结 **20 项开发集（原 13 + 新 7）与 10 项新留出集**。开发集 **8/20（40%）**；留出集 **4/10（40%）**。原 13 项本轮为 5/13，新增 17 项为 7/17。重复次数为每任务一次；此前运行不进入本轮分母。

留出是相对于修复策略调试，任务构造者已查看公开修复来编写评分，不能称为构造者盲测；模型预训练是否包含这些代码未知。第一次结果已公开，若之后根据具体留出失败样例调整策略，应将这些样例转入开发集并补充新的留出任务。

## 准入与独立评分

新增候选固定上游父提交和修复提交，保留元数据、完整源码、许可证和树哈希。评分按任务分为 Target 与 Controls。修复前必须执行到目标测试并失败，同时 Controls 通过；上游修复后两组都必须通过。零项测试、导入/发现失败、跳过或预期失败不能被当作通过。历史 13 项也在同一执行环境重新准入。

审核了 18 个新增候选，准入 17 个。旧 Toolz topk-zero-key 的 before/reference 都有 Python 3.11 不兼容语法，模型调用前排除，改选 join-unmatched；排除记录保留在 [候选目录](experiments/expanded_suite_v1/new-candidates.json)。旧库所需 collections.abc 别名由隔离解释器统一补回，before、reference、candidate 完全相同，不修改上游源码。没有安装新依赖。评分用例为本人编写、参考公开要求和上游回归场景，不是完整上游测试套件。

原始 Target 和 Controls 均不发送给模型。本轮不提供公开测试代码或执行反馈；模型只收到缺陷描述、允许的源码范围和原始检索证据。评分器另建干净的 before 副本，覆盖允许修改的源码后执行测试。必须目标、控制和修改范围同时满足才计成功。所有候选只改 D 盘实验副本，没有发布到实际仓库或服务。

## 统一基线协议

- 本地 Qwen `qwen3.5:27b`，模型 digest 与冻结引擎校验；temperature=0、top_p=1、关闭思考。
- 查询为公开描述加固定 `contract contracts`；完整函数 BM25，最多五个种子、6,000 字符、依赖深度零；没有策略专用查询改写。
- 每任务一次模型调用，Token 上限 15,000，输出上限 2,048；无工具调用和自动重试。
- 所有任务使用唯一原文片段替换，支持严格单 JSON 代码块；补丁后编译修改文件，再独立验收。
- 全部检索证据、任务划分和协议在第一次模型请求前保存；不使用参考补丁选择函数。
- 保留所有 30 个结果，不因失败、无效补丁或检索缺失换任务；本轮没有修复后的再次模型重试。

这是受控实验适配器的效果，不是默认交互 Agent 的完整工具探索能力，也不是 SWE-bench 分数。它与历史两轮反馈、任务专用源码契约等协议不同，因此不能把 40% 与 5/6 当作性能退化的直接证据。

## 成功、回归与成本

最终 **12 项通过、15 项行为验收失败、3 项无效补丁**。Target 单独通过 13 项，Controls 通过 29 项：Toolz interpose-empty 修复了空输入，但破坏了非空输入，按完整规则仍失败。没有预算预检查停止、输出截断或模型传输故障。

30 次全新本地调用，共 **86,075 Token**，用量完整；Worker 累计约 **366.77 秒**，不包含所有准入、检索与独立评分耗时。零 DeepSeek 请求。开发/留出、逐仓库与逐任务统计都保存在机器摘要。

## 失败诊断

运行结束后才用上游 before/after 的函数 AST 差异生成参考标签，未反馈给模型：**21/30 项完整展示了上游修复涉及的既有函数**。18 项失败中，9 项未完整展示这些函数，另 9 项在完整展示情况下仍失败。参考修改不是唯一修复路径，该关联不能证明失败原因；它提供了比继续盯住 none-salt 更广的开发线索。

三项无效补丁分别是非法编辑字段、旧片段不能唯一匹配、尝试编辑未提供上下文的文本。后两项仍被保护机制拒绝，没有记为修复成功。其余失败应再区分检索定位、未修复目标行为与引入回归，而不能统一归因为 Token 预算。

下一步可优先在 **20 项开发集**比较已有的 BM25 与符号优先检索，并检查有界补丁拒绝反馈能否处理协议错误；每次只改一种变量。保持本轮留出集的策略冻结，不据其具体答案调参。未运行这些新优化，本报告只记录完整基线。

## 工程验证与复现

新增工程测试 **6 passed**；Windows 全量 **1,187 passed、2 skipped，208.22 秒**。实现及工程测试 Ruff 通过；已冻结的评分 fixture 仅在专项 lint 中忽略 I001 导入排版规则，以保留运行前哈希，不修改计分输入。未重跑 Linux、容器或 HTTP 验收。

[准入实现](experiments/expanded_admission_v1.py)、[基线执行器](experiments/expanded_baseline_v1.py)、[新增用例目录](experiments/expanded_suite_v1/checks/)均已保存。源码下载、缓存、输出及临时目录在 D 盘，现有 Conda 环境只用于执行。

```powershell
python -m pytest tests/test_expanded_baseline.py -q
python -m docs.experiments.expanded_admission_v1 --output .tmp/real-defects/expanded-admission-user
python -m docs.experiments.expanded_baseline_v1 --admission .tmp/real-defects/expanded-admission-user/admission.json --output .tmp/real-defects/expanded-baseline-user
```

输出目录必须全新，环境需设置 D 盘 TEMP/TMP、PYTHONDONTWRITEBYTECODE=1；执行模型前需要本地 Ollama 和冻结模型。新增源码会从 GitHub 下载，但旧 13 项仍依赖已有准入快照及历史认证工件，不能宣称仅 clone 就可重建全部历史输入。

本轮原始记录：`.tmp/real-defects/expanded-admission-v1-certified-v2/admission.json`、`.tmp/real-defects/expanded-baseline-v1/experiment.json`；证据和答案逐任务保存。`.tmp` 不进入 Git，机器摘要保存了来源哈希。
