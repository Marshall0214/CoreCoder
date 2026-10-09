# 主动迭代器诊断：三项固定预算对照

## 结论（2026-10-09）

当前生成/反馈修正流程 **2/3**，主动诊断/生成流程 **2/3**。
predicate 仍失败，windowed-zero 与 ichunked-zero 成功保留；没有新增或丢失成功。
模型确实自主选了输入，工具正常执行，观察进入实际第二次请求，但没有提高整项修复率。
实际调用和 Token 增加，**不采用、不扩跑**；默认 Agent/API 与完整 32/50 未变。

| 任务 | 当前流程 | 主动诊断 |
| --- | --- | --- |
| more-predicate-sentinel | 第二轮截断，失败 | 完整补丁应用，行为失败 |
| more-windowed-zero | 通过 | 通过 |
| more-ichunked-zero | 通过 | 通过 |

三项全部是已查看的开发任务，同一仓库，一个持续失败与两个历史成功。
不代表三个新失败，也不是泛化评测。

## 做了什么，与固定日志提示有何区别

新增 [受限诊断工具与修复流程](experiments/active_iterator_repair_v1.py)、
[独立执行子进程](experiments/active_iterator_probe_child_v1.py) 与
[三项对照入口](experiments/active_iterator_compare_v1.py)。没有继续使用函数体块协议。

- 第一次模型请求通过 Function Calling 自主选择具体诊断输入，最多两次工具执行。
- 工具只支持 locate、replace、windowed、ichunked；每次 1–4 个例子、数组最多 8 个有界整数，
  窗口/步长等有上限，predicate 只支持预定义的 sum_equals 与 truthy。没有任意 Python 或 shell 参数。
- 独立 Python `-I -B` 子进程执行缺陷源码，记录真实窗口、predicate 参数、输入消费、输出和异常。
  只对 windowed 做保持原输出的观察包装，不捕获其他局部变量；每工具执行超时 15 秒，
  结果和事件有界，源码前后哈希须一致。超出范围拒绝，截断结果显式标为不可用。
- 第二次模型请求接收真实工具消息及认证公开测试，生成一次常规 old/new 补丁。
  沿用原编辑、编译、双重公开验证和失败回滚；worker 完成后再独立 Target/Controls 评分。

原流程两次调用分配为“生成补丁 → 必要时反馈修正”，主动流程分配为“选择探测 → 生成补丁”。
主动流程只生成一个候选，没有改后再探测/再次修正的机会。
这改变了调用分配、观察对象和提示顺序，不是仅增添一个工具的因果消融，也不是多轮交互调试器。
首次提示不同，不声称首轮输入/回答相同；工具不会自动套用作者预定的复现输入。
两组第二阶段均可看到同一认证公开测试，没有参考补丁、私有评分测试或隐藏答案进入工具/模型输入。

## 模型选择和实际失败路径

predicate 请求一次工具执行、两个例子：
`replace([0,1,2,3], sum_equals(3), [99], window_size=3)` 和
`locate([0,1,2,3], sum_equals(3), window_size=3)`。

replace 的真实观察捕获了 `[3, internal_marker, internal_marker]` 被交给 predicate，
并抛出 TypeError；locate 例子返回 `[0]`，没有覆盖短输入尾部路径。
因此工具正常工作，但模型自选的诊断覆盖仍有限。

第二轮返回完整 **286 Token** 补丁，编译与应用通过；公开 locate 的三个串联断言推进，
到 replace 的不匹配保留断言仍报错。
模型把填充过滤与新 predicate 调用加在 replace 的后半段，前面的原始 `if pred(*w)` 未修改。
原始调用先接收对象并抛错，后加过滤根本不会执行。完整输出、真实观察与可应用补丁都不能替代行为修复。
只算整项失败，不把公开断言推进写成独立修复成功。

windowed-zero 选了空/非空数组与 0/-1 窗口四个例子；ichunked-zero 选择两个例子。
总计 **3 次工具执行、8 个模型选择的例子**，三份观察都可用；实际第二次 wire 请求均包含对应 tool 消息。

## 成本与协议

固定 Qwen `qwen3.5:27b`、冻结 Ollama 身份、temperature=0、top_p=1、非思考、同一描述和源码片段。
两组每任务最多两次模型调用、15,000 Token、单次输出 2048、估算上下文 16,000、
源码五段/6000 字符、任务 600 秒；单请求 60 秒、SDK 重试为零，交替执行组顺序。
工具 schema、调用结果和对话历史均进入同一 Token 预算，不重置预算或增加第三次模型调用。

| 指标 | 当前流程 | 主动诊断 |
| --- | --- | --- |
| 独立修复验收 | 2/3 | 2/3 |
| 实际模型请求 | 4 | 6 |
| Prompt Token | 11,450 | 19,533 |
| Completion Token | 3,032 | 1,411 |
| 总 Token | 14,482 | 20,944 |
| 输出截断 | 1 | 0 |
| 额外诊断工具执行 | 0 | 3 |
| Worker 累计耗时 | 103.86 秒 | 50.79 秒 |
| 回滚后 Controls | 3/3 | 3/3 |

共 **10 次新请求、35,426 Token**。预算上限相同，实际开销不同：主动组 Token 增加约 44.6%，
成功任务也需要先诊断再生成，无法享受原流程首轮成功早停。
诊断子进程累计约 0.27 秒，Worker 包含模型与验证时间；本次耗时更短主要伴随长回答减少，
不能当作稳定速度比或以速度代替修复收益。
没有预算预检查停止、网络错误、超时或缺失 worker 结果。
最终 Controls 含失败回滚后的检查，不代表所有候选都保持正常行为。

## 验收与复跑

新增 13 项测试，覆盖有界参数与禁用任意代码、真实窗口/参数/消费记录、零块无限迭代截断、
子进程不继承模型凭据、越界根路径拒绝、两次调用共享预算、工具结果传入补丁请求、
失败回滚、未选择工具或过多调用拒绝；连同冻结反馈测试 **28 passed**。
Windows 全量 **1384 passed、4 skipped（182.43 秒）**，新增文件 Ruff 与 Git diff 格式检查通过。
原基线和本轮实验文件哈希、模型身份与实际 tool 消息已复核；未调用 DeepSeek，未重跑 Docker/HTTP。
子进程是受限诊断执行器，并不宣称提供操作系统级安全沙箱。

机器摘要：[active-iterator-v1.json](active-iterator-v1.json)。原始记录位于 D 盘
`.tmp/real-defects/active-iterator-v1-pilot`。复跑需已有准入/认证快照、独立评分环境和冻结模型，
必须使用全新的输出目录。单元测试不需要真实模型或凭据。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
python -B -m docs.experiments.active_iterator_compare_v1 --output .tmp/real-defects/active-iterator-v1-rerun
```

本轮收尾，不自动增加工具轮次或重试预算。仅证明这一两次调用分配没有净成功收益，
不能据此认定主动诊断普遍无效。若继续，需先验证补丁是否实际修改了触发异常的语句，
并单独控制更多诊断/生成机会的成本，不能靠增加调用制造提升。
