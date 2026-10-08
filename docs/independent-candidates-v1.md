# 固定预算的独立候选筛选 v1

## 结论

五项已知开发任务重新配对：**反馈修正 2/5，独立候选 2/5**。
独立候选新增空 Usage 成功，丢失资源异常处理成功；predicate 与 none-salt 两组仍失败。
没有净修复提升，不采用、不扩跑到 30 项，默认流程与完整 **32/50** 成绩未变。

| 任务 | 反馈修正 | 独立候选 |
| --- | --- | --- |
| click-usage-empty | 失败 | 第二候选通过 |
| click-resource-exception | 修正后通过 | 失败；吞掉正常异常 |
| more-predicate-sentinel | 失败 | 失败 |
| itsdangerous-none-salt | 失败 | 失败 |
| click-style-color-validation | 首轮通过 | 首轮通过 |

## 实现与公平对照

新增 [候选流程](experiments/independent_candidates_v1.py) 与
[对照入口](experiments/independent_candidates_compare_v1.py)。两组固定 Qwen `qwen3.5:27b`、
Ollama 服务和认证输入，各任务共享最多两次调用、15,000 Token、单次 2,048 输出上限、
16,000 估算上下文和 600 秒任务超时。非思考、top_p=1、请求超时 60 秒、SDK 自动重试为零。

- 反馈组：首轮补丁失败后，使用当前候选、完整公开测试与失败观察生成一次修正。
- 独立组：首轮补丁失败后，恢复起始快照，以原始描述和原始代码证据生成第二候选；
  第二次请求不包含第一候选、失败日志或反馈测试代码。两个候选不会合并。
- 两组都仅用认证公开检查和冻结公开检查决定保留，首个满足全部检查的候选即停止；
  运行异常、零测试或不合格补丁不得发布。都失败则回滚，最后才运行独立 Target/Controls 评分。
- 第二候选若源码与第一候选相同，记录重复并复用第一候选的失败结论；不重复执行验证。
  预算不会在候选间重置，非法补丁和截断不会被当成免费请求。

首次请求 temperature=0；为避免确定性重复，**两组**第二次请求均 temperature=0.7。
这是带第二轮采样的新协议，反馈对照也重新运行，不能与此前确定性 2/5 或完整 32/50 直接串成提升曲线。
采样改变的是两个组共同的请求配置；本轮组间干预为第二次调用的用途。
公开测试信息量也随流程不同：独立候选没有获得反馈组的第二轮测试内容，因此这是完整策略对照，
不能单独归因于“从原始源码重启”或采样多样性。

任务沿用模型对照的三个已知失败、两个已知成功，全部属于开发集，一次运行，交替执行组顺序。
五对首轮 wire 请求、首轮回答均完全一致，未重放历史回答。
四项需要第二候选的任务，其两次消息相同，温度不同；四个第二候选源码均不同，重复数为零。

## 成本与失败原因

| 指标 | 反馈修正 | 独立候选 |
| --- | --- | --- |
| 独立修复通过 | 2/5 | 2/5 |
| 请求数 | 9 | 9 |
| Prompt Token | 24,146 | 21,153 |
| Completion Token | 5,343 | 5,151 |
| 总 Token | 29,489 | 26,304 |
| Worker 累计耗时 | 151.08 秒 | 135.00 秒 |
| 最终 Controls | 5/5 | 5/5 |

共 18 次新请求、55,793 Token。独立组 Token 少约 10.8%，主要来自不带失败反馈的较短输入；
修复通过数未增，不能写成修复效果提升。耗时仅是单次本机观察。
18 次回答均为 `stop`，没有输出截断、预算停止、API/网络错误或超时。
最终 Controls 包含失败回滚后的检查，不表示所有生成候选都没有行为回归。

失败证据说明：

- 资源任务的独立第二候选通过缺陷复现，却使正常异常被吞掉；
  `test_exceptional_exit_pops_context` 要求的 `ValueError` 未抛出，公开保持检查拒绝发布。
  反馈组修正通过缺陷复现及全部退出/嵌套 Context 保持检查。
- predicate 反馈补丁把 predicate 返回的布尔值当窗口检查，发生类型错误；
  独立候选仍把填充对象传给 `sum(items)`，短尾部窗口发生类型错误。
  候选能应用、回答完整、源码不同都不能保证修复语义正确。
- none-salt 两组在 Serializer dumps/loads 的盐值关系上仍不一致，触发 `BadSignature`。
  此前确定性流程此项成功，本次采样均失败，不能宣称新策略保留了历史成功。

本轮仅说明两种策略在五项上的成功集合不同；没有证明独立采样普遍无效。
同样，没有证据支持扩大候选数、预算或在这五项上反复调温度。
决策是保留原流程，停止这一小试验，不依据最终评分在两个组之间择优拼接成绩。

## 验收与复跑

新候选流程 10 项测试，覆盖起始快照恢复、共享预算、首轮成功早停、重复候选、
不可用补丁回滚、公开执行异常、冻结检查拒绝及请求参数记录。连同冻结反馈测试 **25 passed**。
Windows 全量 **1352 passed、4 skipped（160.03 秒）**；新增文件 Ruff、Git diff 格式检查通过。
所有冻结源码、测试和协议来源哈希在真实运行后复核通过；未重跑 Docker/HTTP，也未使用 DeepSeek。

机器摘要：[independent-candidates-v1.json](independent-candidates-v1.json)。原始输入、候选、
公开日志、独立评分和请求记录全部位于 D 盘 `.tmp/real-defects/independent-candidates-v1-pilot`。
复跑需要原 50 项准入与认证快照、独立评分环境和冻结 Ollama 模型，并指定新的输出目录；
仅克隆项目不能重建已有真实仓库实验的输入。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
python -B -m docs.experiments.independent_candidates_compare_v1 --output .tmp/real-defects/independent-candidates-v1-rerun
```
