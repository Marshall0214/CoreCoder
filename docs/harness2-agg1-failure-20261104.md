# agg1 失败补丁：原始证据复盘

本轮只整理证据，不修改 Agent、工具、Validator 或模型配置；新增模型调用和测试执行均为 **0**。自主扩权试验到此结束，进入验证与可信性阶段。以下材料来自已经完成的 Toolz 单项实验，不产生新修复成绩。

## 四份材料

| 材料 | 原件或完整副本 |
| --- | --- |
| 1. 原始 join 及相关上下文 | [完整原文件](harness2_agg1_failure_20261104/01_source/itertoolz-original.py.txt)、[完整 join，原813–921行](harness2_agg1_failure_20261104/01_source/join-original.txt)、[模块导入](harness2_agg1_failure_20261104/01_source/module-imports.txt) |
| 2. agg1 完整 Diff | [完整 Diff](harness2_agg1_failure_20261104/02_patch/agg1.diff)、[模型原始编辑响应](harness2_agg1_failure_20261104/02_patch/model-response-011.txt)、[修改后完整 join](harness2_agg1_failure_20261104/01_source/join-candidate.txt) |
| 3. Target 和完整报错 | [原测试，含 Controls](harness2_agg1_failure_20261104/03_test/test_admission.py.txt)、[完整 stderr](harness2_agg1_failure_20261104/03_test/Target.stderr.txt)、[评分记录](harness2_agg1_failure_20261104/03_test/Target.json) |
| 4. 读取到生成补丁的 Trace | [全部11步动作/工具返回](harness2_agg1_failure_20261104/04_trace/actions-complete.json)、[第11次实际请求](harness2_agg1_failure_20261104/04_trace/effective-request-011.json)、[第10步模型响应](harness2_agg1_failure_20261104/04_trace/model-response-010.txt)、[全部事件](harness2_agg1_failure_20261104/04_trace/events-complete.jsonl) |

[证据校验清单](harness2-agg1-failure-20261104.json)记录 SHA256、旧证据完整性和本轮执行边界。有效请求是经过 Context/指导处理后的内容；不拿处理前的 checkpoint 文件冒充最终请求。

## 1. iteritems 不是这次首次发明的标识符

原文件第918行已经包含：

```python
for key, matches in iteritems(d):
    if key not in seen_keys:
        for match in matches:
            yield (match, right_default)
```

这是 Left/Full Join 共用的收尾循环。当前模块没有定义或导入 iteritems，原代码执行此路径本就会发生 NameError。这不等于整个项目或所有 Python 环境都不存在同名工具函数；直接证据是本模块绑定及实际运行错误，不是笼统归因为“模型用了 Python 2 知识”。

模型在新循环中沿用了原有标识符，未补定义/导入，也未修改原调用。因此应区分：**遗留的未定义符号没有修好，同时新增了一处同名错误调用。**仅检查“补丁有没有新增标识符名称”会遗漏这种情况。

## 2. 哪一步读到了什么

| 步骤 | 实际动作/返回 | 能确定的事实 |
| --- | --- | --- |
| 1 | search 找到 join 在813行 | 813是行号 |
| 2 | read_symbol(join, offset=813)，返回3044字符，complete_symbol=false | offset是符号内字符偏移；尾部已含原 iteritems 和公共循环 |
| 3–9 | 多次 read_file(offset=700/813/900/880)，返回文件靠前内容 | 位置理解仍有问题，不是在依次读取目标函数的行范围 |
| 10 | read_symbol(join, offset=0)，返回3857字符，complete_symbol=true | 得到完整813–921行，包括原公共循环 |
| 11 | candidate 阶段，返回一个 edits 数组 | 模型生成插入循环的补丁，执行器按唯一锚点应用 |

首次含 iteritems 的工具返回在第2步；第3次 [实际模型请求](harness2_agg1_failure_20261104/04_trace/effective-request-003.json)已经携带该片段。第11次请求的唯一源码片段与原始完整 join **逐字符相等**，其中原公共循环仍在。因此本例不能归因为“Context Builder 丢掉了函数尾部”。

这些记录只暴露结构化请求、动作和响应，没有内部推理文本。可以确定模型看到了哪些输入并返回什么修改，不能断言某一轮它在内部形成了怎样的信念。

## 3. 原循环为什么仍在，重复输出在哪里引入

原控制流已经是：

```text
Left Join：输出匹配行
Full Join：输出匹配行及未匹配右行
两个分支之后：公共循环输出未匹配左行
```

第11步模型只把 Left Join 的匹配循环选作 old 锚点，并在对应 new 文本末尾增加未匹配左行循环。原公共循环在锚点之外，所以完整保留。

复盘已验证：old 在原文件恰好出现一次；将原始模型 JSON 的该替换应用到原文件后，结果与保存的候选文件完全相同。**不是补丁工具选错位置或额外修改了代码，而是模型要求的修改本身重复了已有行为。**

候选控制流变为：

```text
Left Join：输出匹配行 → 新循环输出未匹配左行
分支之后：原公共循环再次输出未匹配左行
```

Target 在候选第908行首先遇到新增的 iteritems 调用并报错，所以这次运行尚未执行到第二次输出。不能把同一个 NameError 日志当作重复输出已经动态触发的证明。

已有前一轮隔离诊断提供补充证据：只把两个调用改为 d.items()，Target 报未匹配行出现两次；再删除新增循环，两组检查通过。本轮只核对复用，没有重新执行诊断。当前候选与当时诊断候选的 **Python AST 完全一致**（忽略注释、空白、行位置），测试文件哈希也相同；[等价性记录](harness2_agg1_failure_20261104/evidence-findings.json)与 [原诊断报错](harness2_agg1_failure_20261104/prior-counterfactual/candidate_names_only/Target.stderr.txt)保留各自来源。这支持重复行为分析，但不将人工修改计为 Agent 成功。

## 4. 生成指导中的错误解释

合成后的 [Tool Guidance](harness2_agg1_failure_20261104/04_trace/tool_guidance.md)把原因写成未匹配分支中的变量、可能是 right_default，没有初始化，并要求在左侧键循环中修复。

这份解释和实际源码不一致：right_default 是函数参数，Target 也显式传入 None；实际运行未绑定的是 iteritems。该错误描述与完整源码一起进入了第11次请求，属于**已经进入上下文的未经验证诊断**。

它可能把注意力引向“新增分支逻辑”，但没有“移除该指导”的对照，不能声称它就是唯一原因。可以确认的是：本轮没有在生成补丁前程序化检验该解释是否符合源码。

## 5. 为什么执行器没有拦截

当时执行器检查修改结构、可写范围、源码版本、已读取证据、唯一锚点和 Python 语法；满足这些条件就记录 candidate_generated 并结束，再由独立评分器测试。

compile 检查不会执行函数，无法保证运行时名字可解析，也不检查输出次数。该 pilot 也没有可供 Agent 调用的测试工具，不能归因为模型忽略了已经提供的测试按钮。

因此完整链路是：**原有错误符号进入源码上下文 → 错误诊断与源码同时进入候选请求 → 模型复制已有循环到另一个位置 → 结构/语法合法 → 独立测试暴露新增调用的 NameError。**遗漏原公共循环的语义分析是可观察结果，内部为何遗漏仍未知。

## 6. 已知、未知与下一阶段边界

- 已证实：源码尾部没有丢失；遗留错误未修复；第11步新增了重复逻辑；工具忠实应用了模型补丁；语法通过不代表行为正确。
- 未证实：具体内部推理、单个指导或 Context 开关的独立因果贡献、模型是否通过增加推理就能正确修复、其他任务的泛化收益。
- 下一阶段 Validator 应区分基线已有错误、补丁新增错误位置和仍未修好的目标行为。仅禁止新名字或仅做语法检查都不足以覆盖本例。
- 如果未来向 Agent 返回验证反馈，必须来自另行声明的公开验证器；当前独立 Target/Controls 继续后验评分，不能回灌答案后仍宣称沿用原独立验收协议。

本轮仅完成失败归因材料。Patch Validator、验证反馈修正和经验准入协议均未在此轮实现，也没有继续开放修改权限。
