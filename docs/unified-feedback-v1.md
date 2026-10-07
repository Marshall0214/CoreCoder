# 真实任务的统一失败反馈 v1

## 做了什么

新增可选 [统一反馈 Worker](experiments/unified_feedback_worker_v1.py)，把两类失败接入同一条最多两次调用的流程：

1. 生成补丁；统一模式先在副本中执行唯一匹配、Python 编译、新增重复定义和模块加载校验。
2. 编辑被拒绝：原文件不变，反馈简短拒绝原因，并基于原文件刷新证据。编辑通过但公开断言失败：基于已提交的当前候选刷新证据，反馈公开检查失败。
3. 最多修正一次，复用同一个 BudgetLLM 和 15,000 Token 预算；第二次仍失败就停止。
4. 父进程使用独立 Target/Controls 检查最终工作区。独立评分结果不进入模型请求。

第二轮补丁被事务拒绝时，保留第一轮已经提交的候选；不会把未通过校验的第二轮代码写回。源文件变化、导入修改文件、导入超时、写入故障及非预期工具响应不自动重试。公开检查仅在原版本和候选版本都出现有效断言失败时触发反馈；零测试、执行错误和超时不能被当作有效断言失败。

这是固定工作流，不是动态规划或通用反思。默认服务与冻结引擎未修改。

## 真实任务对照

[对照程序](experiments/unified_feedback_v1.py) 使用此前准入的六项真实缺陷，每项每组一次，共 12 个分支、16 次全新模型调用。先运行 none-salt 的两个分支，再运行其余五项的十个分支；两个记录任务集合不重叠，汇总前检查实现哈希、源文件、评分版本及模型身份。

- `public-feedback`：保持已有编辑器与公开断言反馈逻辑，无法应用的第一份补丁停止。
- `unified-feedback`：增加事务校验；事务拒绝或公开断言失败均可使用唯一的一次反馈机会。

两组初始提示、函数证据、允许文件、工具集合、模型与预算相同。使用已有 Ollama `qwen3.5:27b` 的 OpenAI 兼容接口、temperature=0、reasoning_effort=none、输出 2,048、上下文 16,000；没有切换到上一轮原生接口的 thinking 配置。两项有人工公开检查：usage-empty 使用原检查，none-salt 使用已离线认证的 v2 检查。公开失败反馈的内容及上下文刷新保持两组一致，未同时引入日志压缩等新变量。

另外四项没有认证的公开检查，仅做初始修复和独立回归；统一模式只在事务失败时有额外反馈机会。不会使用独立评分为它们补造模型反馈。

## 结果

| 真实任务 | 公开反馈 | 统一反馈 |
| --- | --- | --- |
| click-usage-empty | 通过 | 通过 |
| click-echo-empty-bytes | 通过 | 通过 |
| click-style-color-validation | 通过 | 通过 |
| itsdangerous-none-salt | 未通过独立验收 | 第二轮重复定义被拒绝，独立验收未通过 |
| itsdangerous-future-age | 通过 | 通过 |
| itsdangerous-malformed-time | 通过 | 通过 |

| 指标 | 公开反馈 | 统一反馈 |
| --- | --- | --- |
| 独立验收 | 5/6 | 5/6 |
| 新模型调用 | 8 | 8 |
| 总 Token（返回 usage 完整） | 25,837 | 25,837 |
| Worker 总耗时 | 110.59 秒 | 125.36 秒 |
| 事务拒绝 | 不适用 | 1 次 |

六对初始提示与初始回答均一致，两对公开失败反馈提示也一致。因此本轮没有增加模型成功数或降低 Token；统一流程的新增作用是拦截 none-salt 第二轮的重复 `Serializer.dumps/loads`，并保持第一轮候选字节不变。

none-salt 两组的 Controls 都通过、Target 都失败；不能据此宣称事务保护避免了功能回归。保留下来的第一轮候选仍有参数默认值/None 语义错误，也不能被当作修复完成。新增事务拒绝反馈路径没有在本轮真实第一轮补丁中触发，其工程行为由专项回归及上一轮合成故障对照验证。

耗时为这次单轮观测，包含模型推理、进程启动、校验与公开测试，受缓存及执行顺序影响，不能作为稳定性能比例。六项任务均已被查看过，只运行一次，不是未见任务泛化验证，不与历史重复实验合并计算成功率。

**决策：保留统一流程为可选工程能力，冻结这轮对照；未证明修复率提升，不替换默认服务。** none-salt 的剩余瓶颈是语义修复，后续应对模型或规划/编辑策略作单变量对照，而非继续扩大这组任务的反馈次数。

## 验收和复跑

专项 16 passed；最终 Windows 全量 **999 passed、2 skipped（162.94 秒）**。Ruff、冻结哈希、配对提示及保留候选检查通过。本轮未重跑 Linux、Docker 或真实 HTTP 验收。

机器摘要：[unified-feedback-v1.json](unified-feedback-v1.json)。原始记录位于 `.tmp/real-defects/unified-feedback-v1-pilot` 和 `.tmp/real-defects/unified-feedback-v1-regression`，不进入 Git。真实复跑需要已有准入快照、隔离解释器、独立检查及两份公开检查认证；单元测试不依赖这些历史产物或模型 API。

```powershell
$env:TEMP='D:\project_other\CoreCoder\.tmp\python-temp'
$env:TMP=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='D:\project_other\CoreCoder;D:\project_other\CoreCoder\.tmp\workflow-deps'
python -B -m pytest tests/test_unified_feedback.py -q -p no:cacheprovider --basetemp .tmp/pytest-unified-feedback-rerun
python -B -m docs.experiments.unified_feedback_v1 --task itsdangerous-none-salt --output .tmp/real-defects/unified-feedback-rerun-pilot
python -B -m docs.experiments.unified_feedback_v1 --output .tmp/real-defects/unified-feedback-rerun-all
```

最后一条会完整重跑六项任务，与 pilot 重叠；两次重跑应分别报告，不能把同一任务的 pilot 再并入完整结果。所有输出使用全新目录，工程产物继续放 D 盘。
