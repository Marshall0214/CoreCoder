# 参数转发上下文反馈 v1

本轮完成参数转发上下文策略及三轮真实配对验证，未提高修复成功率：两组均 3/6，usage-empty 均 3/3，none-salt 均 0/3。新策略把 none-salt 的失败从错误默认值转为盐值隔离回归，因此不提升为默认方案。

| 指标 | 原种子反馈 | 参数转发上下文反馈 |
| --- | --- | --- |
| usage-empty | 3/3 | 3/3 |
| none-salt | 0/3 | 0/3 |
| 实际调用 | 12 | 12 |
| 实际 Token | 41,316 | 42,681 |

本轮共 24 次全新调用；新策略 Token 为原反馈的 1.033 倍。六对首轮 Prompt 哈希一致，所有分支最多两次调用，均未超过 15,000 Token；无预算停止或无效补丁。协议、源码哈希和逐次结果见 [机器摘要](repair-forwarding-feedback-v1.json)。这些调用与上轮单次/反馈比较分别报告。

## 问题与改动

公开检查已能指出 none-salt 的错误，但上一轮反馈仍把 Serializer 的显式 None 回退为 Serializer 默认盐值，违反需求中的 Signer 默认盐值关系。原五个 BM25 片段包含两个构造函数和无关的 JWS 构造函数，缺少 Serializer 的参数转发方法。

本轮新增独立实验适配器，不修改冻结的上轮实现、评分或默认服务。`repair_forwarding_worker_v1.py` 在第二次调用前按候选源码重新建立 AST 索引：

1. 根据公开需求解析点名的类，优先保留其构造函数。
2. 在这些类中查找：参数名出现在公开需求、方法读取同名 self 属性、并将该参数名传给属性调用的方法。
3. 优先装填上述方法，再补充原 BM25 种子；保留完整函数、最多五项、6,000 字符及源码哈希校验。

这是参数/状态转发的语法启发式，没有推断正确盐值、写入修复答案或读取参考补丁；也不是完整数据流分析。它不会解析别名、多跳传递、动态派发或继承关系，无法证明变量之间的语义依赖。

none-salt 原始源码离线装填包括 Serializer.__init__、Signer.__init__、Serializer.make_signer、Serializer.iter_unsigners 和原 JWS 构造种子，共 4,840 字符。模型反馈实际读取的是第一轮补丁后的候选源码，逐次片段数量和哈希保留在原始报告中。

## 对照协议

两项已查看的开发任务，各三次配对；两组都使用冻结公开检查、相同首轮输入、最多一次反馈和共享 15,000 Token 上限。唯一干预是第二轮的上下文装填：

| 策略 | 第二轮片段 |
| --- | --- |
| public-feedback | 更新原五个 BM25 种子 |
| forwarding-feedback | 点名类构造函数、参数转发方法优先，再补原种子 |

固定 Ollama qwen3.5:27b、温度 0、reasoning none、Context 16,000、单次输出上限 2,048、唯一原文替换；仅有效公开断言失败对允许反馈，最多两次调用。评分 Target/Controls 独立执行，其输出不作为模型反馈。策略顺序交替；六对首轮 Prompt 哈希必须一致。

同预算上限不保证相同实际消耗。新增的上下文可能挤出原片段，因此对照评估的是整体装填策略，不能将结果独立归因于某一个新增函数。两项任务重复不增加不同缺陷数，也不能代表任意仓库泛化。

## 复跑

先按 [公开检查报告](repair-public-feedback-v1.md) 设置 D 盘临时目录及既有 Conda 环境。需要已冻结的仓库快照、评分环境、公开检查证书及指定模型，Git 不包含这些 .tmp 原始材料。

```powershell
python -B -m pytest tests/test_repair_forwarding_feedback.py tests/test_repair_public_feedback.py -q -p no:cacheprovider --basetemp .tmp/forwarding-tests-user
python -B -m docs.experiments.repair_forwarding_feedback_v1 --output .tmp/real-defects/repair-forwarding-feedback-user --repeat 3
```

真实原始报告：`.tmp/real-defects/repair-forwarding-feedback-v1/experiment.json`。新增产物在 D 盘；没有安装依赖或操作已有用户服务。

## 工程验收

相关回归 23 passed；Windows 全量 924 passed、2 skipped（165.71 秒）；新增适配器与测试 Ruff 通过。测试覆盖点名类与转发方法筛选、无点名类回退、候选哈希刷新、白名单拒绝，以及两种策略相同首轮结构和一次反馈上限。本轮未重跑 Linux、容器或 HTTP 故障验收。

## 失败归因

新片段让模型看到 make_signer 和 iter_unsigners，但失败候选删除了两个方法中 `salt is None` 时采用 `self.salt` 的分支。这样未指定方法级 salt 时，一律交给 Signer 的默认值：None 签名一致性部分看似修好，却同时让不同实例盐值产生兼容签名。

公开 wrong-salt 检查和独立 Controls 都拒绝了该补丁。独立 Target 还发现显式 None 与 Serializer 省略参数的签名不再区分。原策略则保留实例盐值传递，但错误地把构造时的 None 替换为 Serializer 默认值。

不能将“通过 6/7 公开检查”视为成功，也不能只盯住当前失败断言。后续应明确构造参数、省略参数、方法级参数覆盖三者的关系，并同时约束既有签名语义；本轮不增加重试上限、不修改冻结评分。
