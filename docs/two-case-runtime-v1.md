# 两个持续失败案例：机制验证与一次受控修正

## 结论（2026-10-09）

**人工修复假设 2/2 通过独立验收；Agent 两组均 0/2。**
人工补丁不进入模型输入，不计入 Agent 成绩；没有改写完整 32/50 或上一轮 0/3 → 1/3。
本轮不继续追加第三次调用或扩充任务，运行事实策略不采用。

| 案例 | 仅操作检索 | 操作检索＋运行事实 | 未修完整的原因 |
| --- | --- | --- | --- |
| more-range-membership | 失败 | 失败 | 两个第二轮候选相同，仍以余数接近 0 判断成员，0.5 被拒绝 |
| click-prompt-suffix | 独立验收失败 | 独立验收失败 | 两个候选相同，公开 prompt 场景通过，但空后缀 confirm 未修，自定义后缀行为回归 |

## 人工机制验证：只用于说明问题可解

在独立副本上依据缺陷描述与原始源码构造修复假设，没有读取上游参考修复。
代码：[two_case_diagnosis_v1.py](experiments/two_case_diagnosis_v1.py)。

range 的假设让 membership 与 index 使用一致的生成式匹配：在商对应位置附近检查
`start + position * step` 是否等于待查值，并保持范围边界；长度同样按实际生成值检查端点。
这消除了只判断浮点余数等于/接近 0 的问题。十个小范围场景包含正负步长、空范围、
大整数、Decimal、Fraction、datetime，加上非成员拒绝检查，均通过。
这只是有界诊断候选，不宣称所有数值类型、极端浮点或超大范围下的生产正确性/性能。

prompt 的假设根据后缀是否为空决定输入函数是否补空格，并同时修改 confirm 的对应调用。
八个场景涵盖空/普通/自定义后缀、可见/隐藏输入、confirm 与 abort，均通过。
初次扩展检查把普通隐藏输入的预期写成 `Count:\n`，而原有路径保留空格，输出为 `Count: \n`；
纠正这条检查后，人工作业全部通过。不是因隐藏输入失败而修改生产语义。

两个人工候选的当前/冻结公开检查均通过，随后 worker 外独立 Target/Controls 均通过。
原始证据：D 盘 `.tmp/real-defects/two-case-v1-human-final/diagnosis.json`、
`independent-summary.json`；prompt 八项矩阵另存本轮 `post-audit.json`。
人工候选来自原始 before 副本，模型候选来自共享首轮补丁，二者不是相同实验条件，不能比较 Token 或修复率。

## Agent 对照实际做了什么

新增 [公开运行观察器](experiments/two_case_runtime_v1.py)、
[独立执行子进程](experiments/two_case_probe_v1.py) 和
[两项对照入口](experiments/two_case_compare_v1.py)。它们不导入人工修复模块，不读取人工检查输出。

两组重放同一冻结首轮请求和补丁，原始真实 Token 用量计入两组预算；仅第二轮是真实新请求。
两组使用相同失败操作检索片段、系统提示、原公开反馈和验证流程。
实验组只追加真实运行事实：

- 在认证公开 Reproduce/Preserve 中记录 _build_prompt、prompt_func、visible_input/hidden_input 的原始参数。
  只捕获 text/prompt/suffix 的原始基础类型，不捕获用户输入返回值或其他局部变量。
- 从这两类公开测试提取 numeric_range 的字面量参数，对该范围最多 12 个实际生成值执行
  contains/index，记录结果与异常类型，不加入参考答案、修复建议或人工验证结果。
- 构造参数最多四组，提示调用最多 12 条；未知对象不执行 repr/迭代器。
  独立 `-I -B` 子进程，15 秒超时，测试结果数与原公开运行一致，源码/测试哈希前后不变。
- 可用观察分别 1146、927 字符，上限 4000；它们和所有提示一起计入同一任务 Token 预算。

这是针对数值范围与提示输入的手工选择诊断家族，不是通用调试器或操作系统安全沙箱。
额外 contains/index 操作参数只来自可读公开测试，未使用私有 Target/Controls 的输入。
私有评分只在 worker 完成后执行；人工补充场景只在模型运行完后检查候选。

## 原因收敛

### range：当前主要剩余问题是生成的判断逻辑

运行事实已经显示多个“范围实际生成、但 contains/index 拒绝”的数值。
两组仍生成相同余数容差补丁。`divmod(0.5, 0.1)` 的余数接近 0.1，
候选只接受余数接近 0，所以公开测试仍在 0.5 失败。
不能把这次失败归因于 __contains__ 未展示或运行工具没执行。
本轮仅说明追加这些运行事实没有改变候选，不证明该模型永远无法修好。

### prompt：前面的“代码已展示”解释不完整

需求同时提到 prompt 与 confirm。当前片段提供 prompt 和 _build_prompt，**没有 confirm**；
认证公开复现测试也只调用 prompt。因此确实存在另一个 API 的上下文与验证覆盖缺口。
原来只说“关键代码已展示、模型改错位置”不能解释完整任务失败，需要补充这一点。

本轮两组均修好 prompt 的公开空后缀场景，公开当前/冻结检查全部通过，worker 状态 completed。
但模型没有修改 confirm，独立 Target 失败，最终接受数仍为 0。
worker 的 public passed/published 只是该阶段的暂存结果，不是完整任务验收或对用户仓库的发布。

模型还将输入函数固定为不补空格，而不是保持非空后缀的原有交互行为。
模型运行后的八项矩阵显示：两组各 **6/8**，失败项均为空后缀 confirm 和自定义 `?` 后缀 prompt；
人工候选为 **8/8**。独立 Controls 通过也没有覆盖自定义后缀这条回归，不能声称保持所有正常行为。
这些补查结果没有回流给模型，也没有据此再运行第三次修正。

## 输入、成本与可信度

| 指标 | 仅操作检索 | ＋运行事实 |
| --- | ---: | ---: |
| 独立整项验收 | 0/2 | 0/2 |
| 新模型请求 | 2 | 2 |
| 新请求 Token | 6189 | 6895 |
| 含首轮重放的预算 Token 合计 | 11066 | 11772 |
| 最终独立 Controls | 2/2 | 2/2 |

共四次新请求、13,084 Token；追加观察增加约 11.4% 新请求 Token，没有整项成功收益。
保持 Qwen qwen3.5:27b、冻结身份、非思考、temperature=0、top_p=1；
每任务最多两次调用（含重放）、15,000 Token、单次输出 2048、五段/6000 源码字符、600 秒 worker。
所有真实回答 stop，没有截断、预算停止、网络错误或缺失 worker。
两组初始补丁相同，去掉观察字段后第二轮 payload 相同，两组第二轮候选快照也完全相同。

另有一项重复性限制：prompt 基线第二轮请求与上一轮请求字节完全相同，
本轮回答却从仅撤销 _build_prompt 修改变成同时修改 prompt_func。
冻结模型与 temperature=0 不保证跨次 GPU 推理回答逐字一致；原因没有进一步定位。
因此不能把本轮公开 prompt 通过归因于新增运行事实，尤其本轮对照两组补丁相同。

相关测试 **30 passed**；Windows 全量 **1418 passed、4 skipped（163.03 秒）**；新增文件 Ruff 通过。
冻结输入及原基线哈希前后核对通过。未调用 DeepSeek 或 Docker/HTTP，全部记录在 D 盘。

## 到此收尾

两个问题已分别确认可解与失败机制，不继续靠扩大同类日志制造“进展”。
下一项如继续，应先检查需求里明确提到的多个 API 是否都进入上下文、公开验证是否覆盖这些 API，
优先补 prompt/confirm 的覆盖缺口；这与数值计算逻辑是两类问题，应分开评价。
不能用人工补丁替换 Agent 候选后报告系统成功，也不能把公开 prompt 通过写成整项修复。

机器摘要：[two-case-runtime-v1.json](two-case-runtime-v1.json)。模型原始记录：
`.tmp/real-defects/two-case-runtime-v1-pilot`。复跑必须使用全新目录。

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:TEMP='D:\project_other\CoreCoder\.tmp'
$env:TMP=$env:TEMP
python -B -m docs.experiments.two_case_diagnosis_v1 --output .tmp/real-defects/two-case-human-rerun
python -B -m pytest tests/test_two_case_runtime.py tests/test_predicate_runtime.py tests/test_frozen_feedback.py -q --basetemp .tmp/two-case-tests-rerun
python -B -m docs.experiments.two_case_compare_v1 --output .tmp/real-defects/two-case-paired-rerun
```
